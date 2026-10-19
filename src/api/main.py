"""FastAPI app: POST /ask and GET /health. A thin wrapper around answer_question().

Local demo only: no authentication, so it listens on 127.0.0.1 (see src/api/__main__.py).
Providers are chosen by the same environment variables as the CLI (src/providers/factory.py)
and built once at startup, so a missing setting stops the server instead of failing later.
Logs are JSON lines with names and numbers only: never the question, keys or error text.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from src.answering import answer_question
from src.api.schemas import AskRequest, ErrorResponse, HealthResponse
from src.models import Answer
from src.providers import factory
from src.providers.base import Embedder, Generator, Reranker, VectorStore

logger = logging.getLogger("api")

UPSTREAM_ERROR = "An upstream service failed. See the server log."


@dataclass
class Services:
    embedder: Embedder
    store: VectorStore
    reranker: Reranker | None
    generator: Generator
    names: dict[str, str]  # embedder, vector_store, reranker: the choices they were built from


def build_services() -> Services:
    """Build the providers from environment variables, as scripts/ask.py does."""
    names = factory.selected()
    namespace = factory.pinecone_namespace() if names["vector_store"] == "pinecone" else ""
    embedder = factory.build_embedder()
    return Services(
        embedder=embedder,
        store=factory.build_store(embedder, namespace=namespace),
        reranker=factory.build_reranker(),
        generator=factory.build_generator(),
        names=names,
    )


def provider_names(services: Services) -> dict[str, str]:
    """Names only, for /health and the startup log, e.g. {"embedder": "pinecone", ...}."""
    return {**services.names, "generator": services.generator.name}


def create_app(services: Services | None = None) -> FastAPI:
    """Tests pass fake `services`; otherwise they are built from the environment at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is None:
            app.state.services = build_services()
        logger.info("api started", extra=provider_names(app.state.services))
        yield

    app = FastAPI(
        title="doc-rag-pipeline",
        version="0.1.0",
        description=(
            "Answers questions from public EMA product information, with citations. "
            "Local demo only: no authentication. Not medical advice."
        ),
        lifespan=lifespan,
    )
    if services is not None:
        app.state.services = services

    @app.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid.uuid4().hex
        start = time.perf_counter()
        status_code = 500  # kept when the handler raises
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            logger.info(
                "request",
                extra={
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,  # no query string, no body
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.post(
        "/ask",
        response_model=Answer,
        responses={502: {"model": ErrorResponse, "description": "An upstream service failed"}},
    )
    def ask(body: AskRequest, request: Request) -> Answer | JSONResponse:
        """Answer a question from the indexed documents, with citations and a disclaimer."""
        s: Services = request.app.state.services
        try:
            return answer_question(
                body.question,
                s.embedder,
                s.store,
                s.generator,
                top_k=body.top_k,
                reranker=s.reranker,
            )
        except Exception as error:
            # Only the class name: messages from SDKs can contain index names or request data.
            logger.error(
                "answer failed",
                extra={
                    "request_id": request.state.request_id,
                    "error_type": type(error).__name__,
                },
            )
            content = ErrorResponse(detail=UPSTREAM_ERROR, request_id=request.state.request_id)
            return JSONResponse(status_code=502, content=content.model_dump())

    @app.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        """Liveness and the provider names. Calls no external service."""
        return HealthResponse(status="ok", **provider_names(request.app.state.services))

    return app


app = create_app()
