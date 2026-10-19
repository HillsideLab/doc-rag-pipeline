# Image for the local API demo. Built and run locally only; never pushed to a registry.
#   docker build -t doc-rag-api .
#   docker run --rm -p 127.0.0.1:8000:8000 --env-file .env doc-rag-api
# The server listens on 0.0.0.0 inside the container (needed for port publishing), and
# -p 127.0.0.1:8000:8000 publishes it on the host's loopback only (there is no authentication).
FROM python:3.12-slim

# uv pinned to the version used for development; it installs exactly what uv.lock lists.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# Dependencies first, so editing src/ does not reinstall them. No dev tools in the image.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY src/ src/

RUN useradd --create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["python", "-m", "src.api", "--host", "0.0.0.0"]
