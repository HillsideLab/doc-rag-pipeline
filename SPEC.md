# SPEC: doc-rag-pipeline (prototype)

A small, honest prototype of an event-driven document-processing and RAG pipeline on AWS.
Purpose: get hands-on with a specific stack (Textract, Pinecone, Step Functions, Terraform, FastAPI, Bedrock) and be able to explain every design choice.
This is a learning prototype built from **public documents only**. It is not production software and must never be described as such.

## 1. Non-goals

- No real company data, no proprietary code. Public PDFs only (e.g. drug label / SmPC documents). PDFs are NOT committed; the README lists download links.
- No AWS Batch, GPU, OpenShift, KMS, React UI, multi-tenancy, or auth platform.
- No OpenSearch Serverless, NAT Gateway, provisioned throughput, or VPC for Lambda (cost traps).

## 2. Constraints and environment

- Region: `us-east-1`, always read from `AWS_REGION` (never hard-code). Profile: `AWS_PROFILE=rag-mock` (least-privilege IAM user, already configured on the developer machine).
- Python 3.12 managed with `uv`. FastAPI + Pydantic v2, pytest, ruff.
- **Bedrock access is currently blocked by an AWS account restriction** (support case open). Therefore every external model call sits behind an interface (see section 5). A component may only be labeled "verified" in the README after a real call has succeeded.
- Budget: keep total AWS spend under about 10 USD. Cache Textract output in S3 and never re-run it needlessly.

## 3. Scope tiers (build in this order, stop when time runs out)

**Tier 1 (must):** local pipeline + API
extract (Textract) -> chunk -> embed -> index (Pinecone) -> `/ask` with citations; pytest; Dockerfile; GitHub Actions CI; README with diagram and a "Verified components" table.

**Tier 2 (core, build right after M2/M3; this mirrors the job's event-driven pipeline):** event-driven automation + IaC
S3 upload -> EventBridge -> Step Functions -> Lambda; DynamoDB status table; retries (max 3) and failure state; Terraform for all of it; Secrets Manager for the Pinecone key.

**Tier 3 (if time):** small eval set (retrieval hit@k, vector vs keyword), extraction strategy comparison (text-only vs tables, with per-page cost), JWT bearer check on the API, OpenAPI spec exported to `docs/openapi.json`, VLM vs Textract on one chart/table page.

## 4. Architecture

```
PDF uploaded to S3 (prefix incoming/)
  -> EventBridge rule (Object Created)
  -> Step Functions (Standard)
       RegisterDocument  (DynamoDB: RECEIVED)
       Extract           (Textract async job; raw JSON cached in S3 under textract-cache/<sha256>.json)
       Chunk             (structure-aware chunks + metadata)
       EmbedAndIndex     (embeddings -> Pinecone upsert)
       MarkIndexed       (DynamoDB: INDEXED)
       Catch -> MarkFailed (DynamoDB: FAILED + error message)
       Retry: max 3 attempts, exponential backoff, on transient errors only

FastAPI
  POST /documents            register an S3 key and start the pipeline (Tier 1: runs inline/local)  [not implemented]
  GET  /documents/{doc_id}   processing status  [not implemented]
  POST /ask                  {question, top_k} -> {answer, citations[{chunk_id, file, product, section, page, chunk_type}], generator, disclaimer}
  GET  /health               liveness + dependency checks (no secrets in output)
```

Tier 1 runs the same pipeline functions locally (CLI or API call). Tier 2 wraps those same functions in Lambda handlers. Keep business logic in plain Python modules; Lambda handlers stay thin.

## 5. Provider interfaces (so a blocked service never blocks the project)

| Interface | Implementations | Notes |
|---|---|---|
| `Extractor` | `TextractExtractor`, `FakeExtractor` (fixture JSON) | Textract is a separate service from Bedrock |
| `Embedder` (dim 1024) | `BedrockTitanEmbedder` (amazon.titan-embed-text-v2:0), `PineconeInferenceEmbedder`, `FakeEmbedder` | Pick ONE embedder per index. Switching embedders requires re-indexing; document this in the README. |
| `VectorStore` | `PineconeStore` (primary), `InMemoryStore` (numpy cosine) | Pinecone Starter plan is free but us-east-1 only and pauses after inactivity |
| `Generator` | `BedrockClaudeGenerator` (inference profile ID, not bare model ID), `AnthropicApiGenerator` (optional), `StubGenerator` | `StubGenerator` returns the top chunks with citations (extractive answer). It is the default in tests and when no LLM is configured. |

Selection by environment variables (`EMBEDDER`, `VECTOR_STORE`, `GENERATOR`). Defaults must work with no network access (fakes).

## 6. Data model

DynamoDB table `documents` (on-demand): `doc_id` (PK), `s3_key`, `status` (RECEIVED | EXTRACTING | CHUNKED | INDEXED | FAILED), `attempts`, `page_count`, `chunk_count`, `error`, `created_at`, `updated_at`.
Pinecone vector metadata: `doc_id`, `source_file`, `page`, `chunk_type` (text | table), `section`, `text` (truncated), `embedder`.

## 7. Extraction and chunking

- Textract async API (StartDocumentAnalysis / GetDocumentAnalysis) on PDFs in S3 under `raw/`. FeatureTypes is fixed to `LAYOUT` (about 0.004 USD per page): it gives reading order and headings, but no table cells, so `tables` stays empty and table text comes through as normal lines. Adding `TABLES` is compared in Tier 3.
- Cache raw Textract JSON in S3 at `textract-cache/<sha256 of the PDF>.json`. On a cache hit Textract is not called.
- Chunking: group lines into paragraphs per page, split by size (about 500 tokens, small overlap). Tables are kept whole and rendered as Markdown. Every chunk carries page and type metadata.

## 8. Security and operations

- Secrets: Pinecone key in AWS Secrets Manager (secret container created by Terraform, value set manually, never in Terraform state or git). Locally via `.env` (git-ignored); commit only `.env.example`.
- IAM: one least-privilege role per Lambda; S3 bucket with public access blocked and server-side encryption; bucket name `doc-rag-mock-<suffix>`.
- Logging: structured JSON logs with `request_id`/`doc_id`; log ingest and query events (audit-style); `/health` endpoint.
- Tag all resources `Project=doc-rag-mock`. Provide `scripts/cleanup.sh` and document `terraform destroy`.

## 9. Testing and CI

- Unit tests use fakes only; no real AWS or network calls. Integration tests are marked `@pytest.mark.integration` and are opt-in.
- GitHub Actions (no AWS credentials): `ruff check`, `pytest`, `terraform fmt -check`, `terraform validate`.

## 10. Milestones (one at a time; show a plan before each)

- M0: repo skeleton, uv project, ruff, pytest, CI, `.gitignore`, `.env.example`.
- M1: models + interfaces + fakes + chunking, fully unit-tested.
- M2: Textract integration with S3 caching (verify with a real small PDF).
- M3: embedder + Pinecone store (verify with a real call; keep dimension 1024).
- M4: `/query` logic with generator selection and citations (keep it small; StubGenerator by default).
- M6 (do BEFORE M5): Lambda handlers, Step Functions (Textract async: start, wait, poll, get), DynamoDB, EventBridge, Terraform (`plan` first, then ask before `apply`). Does not need Bedrock.
- M5: FastAPI endpoints, Dockerfile, Pydantic schemas (minimal is fine).
- M7: README (diagram, run steps, cost notes, cleanup, "Verified components" table, honest limitations), `docs/ARCHITECTURE.md` in Japanese.

### Notes for M6 (Tier 2)

- The ingestion pipeline (Textract, chunking, Pinecone embeddings, Pinecone upsert, DynamoDB) must not depend on Bedrock. While Bedrock is blocked, use `PineconeInferenceEmbedder` as the Embedder.
- IAM: the `rag-mock` user needs extra permissions for Terraform. Propose a separate policy scoped to resource names `doc-rag-mock-*` (Lambda, Step Functions, DynamoDB, EventBridge, S3, Secrets Manager, CloudWatch Logs, and IAM roles with that prefix only). Never ask for `AdministratorAccess`. Show the policy to the user before it is created.
- Lambda: Python 3.12, no VPC, no NAT Gateway. Keep dependencies small (`boto3` is built in; package `pydantic` and the Pinecone client). Do not package numpy.
- Secrets: the Pinecone key is read from Secrets Manager at runtime. Terraform creates only the empty secret container.
- Tag everything `Project=doc-rag-mock`. Provide `terraform destroy` and `scripts/cleanup.sh`. Set CloudWatch Logs retention to 7 days.
- Cost guard: tell the user before running the first real pipeline on a PDF; use a small PDF for trial runs (cached results cost nothing).

## 11. Definition of done

- Tier 1: from a clean clone, README steps ingest one public PDF and answer a question with page citations; CI is green.
- Tier 2 (priority): uploading a PDF to S3 triggers the workflow; status is visible in DynamoDB; a forced failure ends in FAILED after 3 attempts; everything is created and destroyed by Terraform.
- README states honestly which components were actually run against real services.

## 12. Differences from the implementation (as of M7)

This spec is kept as written. Where the code differs, this list is the record.

- Section 4, API: `POST /documents` and `GET /documents/{doc_id}` are not implemented. Ingestion starts from an S3 upload to `incoming/`, and the status is read from DynamoDB. Local ingestion uses the CLI (`scripts/extract_pdf.py`, `scripts/index_documents.py`), not the API.
- Section 4, `/health`: returns the provider names only and calls no external service (no dependency checks), so it does not use the rerank quota or cost money.
- Section 4, state names: the states are RegisterDocument -> StartExtraction -> Wait -> CheckExtraction -> SaveExtraction -> IndexDocument -> MarkIndexed / MarkFailed. Chunking, embedding and upsert run in one Lambda (IndexDocument).
- Section 5: `BedrockTitanEmbedder` is not implemented (Bedrock is blocked); `PineconeInferenceEmbedder` is the only real embedder. A `Reranker` interface (Pinecone) and the `RERANKER` variable were added. `AnthropicApiGenerator` is implemented and verified, and replaces Bedrock for generation.
- Section 6: the table is `doc-rag-mock-documents`. Only `RECEIVED`, `INDEXED` and `FAILED` are written (`EXTRACTING` and `CHUNKED` exist in the enum but are never set). Extra fields: `sha256`, `execution_arn`, `textract_cached`, `cause`. `attempts` counts executions for the document, not Step Functions retries.
- Section 6: the Pinecone metadata `text` is stored whole (up to about 3,400 characters), not truncated.
- Section 7: chunk size is 500 words (split on whitespace) with a 50-word overlap, as an approximation of tokens.
- Sections 8 and 11: the S3 bucket existed before Terraform. Terraform manages only its EventBridge notification, so the bucket's encryption and public access block are not managed by Terraform, and `terraform destroy` does not remove the bucket.
- Section 8, logging: the API logs request metadata only (no question text, by design). The Lambda handlers log one JSON line per step.
- Section 9: CI also runs `ruff format --check`, the `docs/openapi.json` check, and builds the Lambda zip for `terraform validate`.
- Section 3, Tier 3: done are the retrieval hit@k evaluation (without a keyword comparison) and the OpenAPI export. Not done: JWT check, LAYOUT vs TABLES comparison, VLM vs Textract.
- Section 10: M4 is `/ask` (not `/query`).
