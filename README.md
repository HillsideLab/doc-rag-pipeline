# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It uses public documents only and is not production software. See `SPEC.md` for scope.

Status: work in progress (milestone M2, Textract extraction). No component has been verified
against real services yet.

## Verified components

A component is marked "verified" only after a real call has succeeded.

| Component | Status |
|---|---|
| Textract (AnalyzeDocument LAYOUT, async) + S3 cache | not verified yet |
| Bedrock | blocked by an AWS account restriction |

## Documents

Public documents only. PDFs are not committed; download them into `data/pdfs/` (git-ignored).

- (to be added: download links for the 2 to 3 public PDFs used)

## Extract one PDF with Textract

Costs about 0.004 USD per page on the first run (AnalyzeDocument LAYOUT, us-east-1; check the
AWS pricing page). The raw JSON is cached in S3 by the PDF's sha256, so re-running the same
PDF does not call Textract again. The script asks before starting a paid job.

```
# .env needs AWS_PROFILE, AWS_REGION and S3_BUCKET
uv run --env-file .env python -m scripts.extract_pdf data/pdfs/<file>.pdf
```

Output: `data/extracted/<doc_id>.json` (an `ExtractedDocument`).

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
