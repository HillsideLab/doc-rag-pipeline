# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It is not production software. See `SPEC.md` for scope.

- **Public documents only.** The only inputs are product information documents published by
  the European Medicines Agency (EMA). No company-internal or proprietary data is used.
- **Not medical advice.** This is a technical prototype. Its answers are not medical advice
  and must not be used for any clinical or treatment decision.

Status: work in progress (milestone M6, event-driven pipeline on AWS). See "Verified components"
for what has been run against real services.

## Verified components

A component is marked "verified" only after a real call has succeeded.

| Component | Status |
|---|---|
| Textract (AnalyzeDocument LAYOUT, async) + S3 cache | verified 2026-10-19 (Cablivi 39 pages, Aubagio 50 pages; re-run served from the cache) |
| Pinecone Inference API embeddings (`llama-text-embed-v2`, 1024 dims) | verified 2026-10-19 (335 chunks from the 2 documents) |
| Pinecone dense index: upsert, re-index without stale chunks, query with `doc_id` filter | verified 2026-10-19 (re-indexing kept 335 records; integration test removed stale chunks in a test namespace) |
| Pinecone reranking (`bge-reranker-v2-m3`, top 50 vector hits) | verified 2026-10-19 (5 requests) |
| Answering with `StubGenerator` (no generative model) over Pinecone retrieval + reranking | verified 2026-10-19 (5 evaluation questions) |
| Event-driven pipeline, cache-hit path: S3 `incoming/` -> EventBridge -> Step Functions -> Lambda (Register -> Index) -> DynamoDB `INDEXED`, Pinecone namespace `pipeline` | verified 2026-10-19 (Cablivi, 39 pages, 138 chunks, same count as the M3 index; Textract skipped by the cache) |
| Failure path for a non-retryable error: Catch -> `MarkFailed` (DynamoDB `FAILED` + error), no retry | verified 2026-10-19 (first run failed on a missing Lambda setting, `PINECONE_EMBED_MODEL`; a text file uploaded as `incoming/x.pdf` failed once in CheckExtraction with `TextractJobError` (`INVALID_IMAGE_TYPE`) and was not retried) |
| Pipeline cache-miss path: StartExtraction -> Wait -> CheckExtraction -> SaveExtraction (writes the Textract cache) -> Index | verified 2026-10-19 (Cablivi medicine overview, 3 pages, 12 chunks; Textract finished within the first 10 s wait, so the IN_PROGRESS loop back to Wait has not run for real; the cache write did not start another execution) |
| Retries of transient errors (3 attempts in total, then `FAILED`) | verified 2026-10-19 (forced with `force_fail_step = "index"`: IndexDocument ran 3 times, with waits of 2 s and 4 s, then MarkFailed set `FAILED` / `TransientError`; Pinecone was not touched) |
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

## Answering questions

`src/answering.py` runs: embed the question -> search (optionally reranked) -> generator ->
answer. Every answer has citations (`chunk_id`, file, product, section, page, chunk type), a
`generator` field, and a fixed `disclaimer` (not medical advice) that does not depend on any
model output.

Providers are chosen by environment variables; the defaults need no network and no keys.

| Variable | Values | Default |
|---|---|---|
| `EMBEDDER` | `fake`, `pinecone` | `fake` |
| `VECTOR_STORE` | `memory`, `pinecone` (needs `EMBEDDER=pinecone`) | `memory` |
| `RERANKER` | `none`, `pinecone` | `none` |
| `GENERATOR` | `stub`, `bedrock` (not verified) | `stub` |

```
export EMBEDDER=pinecone VECTOR_STORE=pinecone RERANKER=pinecone GENERATOR=stub
uv run --env-file .env python -m scripts.ask "What are the excipients of Cablivi?"
uv run --env-file .env python -m scripts.eval_answers     # 5 questions, citation check
```

`StubGenerator` (the default) uses no generative model, and its answer says so on the
first line. It lists every retrieved chunk (`top_k`, default 5) as a numbered passage with its
source. It cannot judge whether the passages actually answer the question; it reports
"No relevant passages were found." only when retrieval returns nothing.

`BedrockClaudeGenerator` instructs the model to answer only from the given passages, to reply
"I don't know based on the provided documents." when they do not contain the answer, and to
cite passages as `[n]`. It needs `BEDROCK_INFERENCE_PROFILE_ID` (an inference profile ID, not
a bare model ID). It has not been run against Bedrock.

Result on the 5 evaluation questions (StubGenerator, Pinecone + reranking, `top_k=5`): 5/5
answers cite at least one expected chunk; the mean share of expected chunks cited is 0.85.
This matches retrieval hit@5 with reranking, because the stub cites every retrieved chunk.
One run used 66 embedding tokens and 5 rerank requests.

## Event-driven pipeline (M6, in progress)

Uploading a PDF to `s3://$S3_BUCKET/incoming/` starts a Step Functions workflow. Its states,
retries and failure handling are in `infra/statemachine.asl.json`, and the infrastructure is
in `infra/` (Terraform, local state). Status is kept in the DynamoDB table
`doc-rag-mock-documents`. Chunks go to the Pinecone namespace `pipeline`, so the M3 data in the
default namespace is left untouched. Full run steps, cost notes and cleanup come with M7.

Measured on the first successful run (Cablivi, cache hit, cold start): the whole execution
took 8 s. Lambda RegisterDocument ran for 1.9 s with 116 of 256 MB used. Lambda
IndexDocument (138 chunks) ran for 3.9 s with 158 of 1024 MB used, and its timeout is 300 s.
On the cache-miss run (3 pages), the whole execution took 27 s. StartExtraction and
CheckExtraction each used 104 of 128 MB, and SaveExtraction used 116 of 1024 MB.

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
