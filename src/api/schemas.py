"""Request and error bodies of the HTTP API. The /ask response is `src.models.Answer` itself."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

MAX_QUESTION_CHARS = 1000

Question = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS),
]


class AskRequest(BaseModel):
    question: Question = Field(examples=["What are the excipients of Cablivi?"])
    top_k: int = Field(default=5, ge=1, le=20, description="number of passages to cite")


class ErrorResponse(BaseModel):
    detail: str
    request_id: str


class HealthResponse(BaseModel):
    """Liveness and the configured providers by name. No external service is called."""

    status: str
    embedder: str
    vector_store: str
    reranker: str
    generator: str
