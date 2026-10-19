# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It is not production software. See `SPEC.md` for scope.

- **Public documents only.** The only inputs are product information documents published by
  the European Medicines Agency (EMA). No company-internal or proprietary data is used.
- **Not medical advice.** This is a technical prototype. Its answers are not medical advice
  and must not be used for any clinical or treatment decision.

Status: work in progress (milestone M3, embeddings and Pinecone). See "Verified components"
for what has been run against real services.

## Verified components

A component is marked "verified" only after a real call has succeeded.

| Component | Status |
|---|---|
| Textract (AnalyzeDocument LAYOUT, async) + S3 cache | verified 2026-10-19 (Cablivi 39 pages, Aubagio 50 pages; re-run served from the cache) |
| Pinecone Inference API embeddings (`llama-text-embed-v2`, 1024 dims) | verified 2026-10-19 (335 chunks from the 2 documents) |
| Pinecone dense index: upsert, re-index without stale chunks, query with `doc_id` filter | verified 2026-10-19 (re-indexing kept 335 records; integration test removed stale chunks in a test namespace) |
| Pinecone reranking (`bge-reranker-v2-m3`, top 50 vector hits) | verified 2026-10-19 (5 requests) |
| Bedrock | blocked by an AWS account restriction |

## Retrieval quality

Measured with `scripts/eval_retrieval.py` on 5 questions (`eval/retrieval_questions.json`).
A question is a hit@5 when at least one expected chunk is in the top 5; recall@5 is the share
of expected chunks in the top 5. Expected chunks are the matching SmPC sections (plus the
leaflet section for the pregnancy question). The set is tiny and the expected chunks were
chosen by the developer, so these numbers show a trend, not a benchmark.

| Stage | hit@5 | mean recall@5 |
|---|---|---|
| Embedded text "section: body" | 1/5 | 0.15 |
| Heading no longer repeated; batches sorted by length (token cost only) | 1/5 | 0.15 |
| Embedded text "Product \| section: body" (product from the EMA file name) | 4/5 | 0.45 |
| Same, plus reranking of the top 50 vector hits | 5/5 | 0.85 |

Known weakness: the leaflet's table of contents chunk ("What is in this leaflet") ranks high
for many questions without reranking. It has not been removed.

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

## Index and search with Pinecone

Uses the Pinecone free (Starter) plan: a dense serverless index (1024 dims, cosine, aws
us-east-1) and the hosted Inference API. Textract is not called; the input is the cached
`data/extracted/*.json`. One full index of the 2 documents uses about 68,000 embedding tokens
(free plan: 5M per month). One index uses one embedding model; switching models requires
re-indexing everything.

```
# .env needs PINECONE_API_KEY and PINECONE_INDEX
uv run --env-file .env python -m scripts.index_documents          # asks before writing
uv run --env-file .env python -m scripts.search "Can Aubagio be used during pregnancy?" --rerank
uv run --env-file .env python -m scripts.eval_retrieval --rerank  # hit@5 / recall@5
```

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
