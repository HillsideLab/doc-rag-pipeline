# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It is not production software. See `SPEC.md` for scope.

- **Public documents only.** The only inputs are product information documents published by
  the European Medicines Agency (EMA). No company-internal or proprietary data is used.
- **Not medical advice.** This is a technical prototype. Its answers are not medical advice
  and must not be used for any clinical or treatment decision.

Status: work in progress (milestone M2, Textract extraction). See "Verified components" for
what has been run against real services.

## Verified components

A component is marked "verified" only after a real call has succeeded.

| Component | Status |
|---|---|
| Textract (AnalyzeDocument LAYOUT, async) + S3 cache | verified 2026-10-19 (Cablivi 39 pages, Aubagio 50 pages; re-run served from the cache) |
| Bedrock | blocked by an AWS account restriction |

## Documents

Public documents only. PDFs are not committed; download them into `data/pdfs/` (git-ignored).

| File | Pages | Source (EMA EPAR page, "Product information") |
|---|---|---|
| `cablivi-epar-product-information_en.pdf` | 39 | https://www.ema.europa.eu/en/medicines/Human/EPAR/cablivi |
| `aubagio-epar-product-information_en.pdf` | 50 | https://www.ema.europa.eu/en/medicines/human/EPAR/aubagio |

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
