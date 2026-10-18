# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It uses public documents only and is not production software. See `SPEC.md` for scope.

Status: work in progress (milestone M0, project skeleton). No component has been verified
against real services yet.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv automatically.

```
uv sync
cp .env.example .env   # optional; defaults use offline fakes
```

## Test and lint

```
uv run pytest                    # unit tests, no network
uv run pytest -m integration     # real services, opt-in
uv run ruff check . && uv run ruff format --check .
```
