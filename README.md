# doc-rag-pipeline

A small learning prototype of an event-driven document-processing and RAG pipeline on AWS.
It is not production software. See `SPEC.md` for scope.

- **Public documents only.** The only inputs are product information documents published by
  the European Medicines Agency (EMA). No company-internal or proprietary data is used.
- **Not medical advice.** This is a technical prototype. Its answers are not medical advice
  and must not be used for any clinical or treatment decision.

Status: work in progress (milestone M5, local HTTP API; M6, the event-driven pipeline on AWS,
is done). See "Verified components" for what has been run against real services.

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
| Lambda logs as JSON (`log_format = "JSON"`): every line in the log group is JSON; `step`, `status`, `document_id` and `execution_arn` are top-level fields | verified 2026-10-19 (read with `aws logs filter-log-events`; CloudWatch Logs Insights queries were not tried) |
| HTTP API on 127.0.0.1 (FastAPI): `POST /ask` from the Swagger UI, `StubGenerator` over Pinecone retrieval + reranking; `GET /health` | verified 2026-10-19 (1 `/ask` request: 200 in 3.9 s; the citations included Cablivi 6.1 List of excipients, pages 10 and 11; the log line had no question text) |
| Docker image of the API (`python:3.12-slim`, locked runtime dependencies, non-root) | verified 2026-10-19 (built locally, 392 MB; container started with `--env-file .env` and `/health` returned the Pinecone providers; `/ask` was not sent through the container; not pushed) |
| `BedrockClaudeGenerator` (Converse API, inference profile ID) | **not verified**: written and unit-tested with a fake client only; never called for real |
| Bedrock | blocked by an AWS account restriction |
| `AnthropicApiGenerator` (Anthropic API, official SDK, `claude-haiku-5-5`) over Pinecone retrieval + reranking, via `POST /ask` from the Swagger UI | verified 2026-10-19 (1 `/ask` request: 200 in 5.7 s, of which generation 1.7 s; 712 input and 115 output tokens, `stop_reason` `end_turn`, 5 passages cited; the `[n]` marks matched the citations; the log had no question text, passage text, answer text or key) |

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
| `GENERATOR` | `stub`, `bedrock` (not verified), `anthropic` | `stub` |

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

`AnthropicApiGenerator` sends the same prompt (`src/prompting.py`) to Claude through the
Anthropic API with the official `anthropic` SDK. Bedrock was blocked by an account
restriction, so the generator adapter was swapped: `GENERATOR=anthropic` is the only change,
and the API code is the same. It needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (no default
in code; `claude-haiku-5-5` is the suggested model). The citations are not written by the
model: they are every retrieved passage in retrieval order, so `[n]` in the answer is always
the n-th citation. A reply cut off at the token limit, or refused, is an error (502), never a
partial answer. The log line per call has the model name and token counts only.

Result on the 5 evaluation questions (StubGenerator, Pinecone + reranking, `top_k=5`): 5/5
answers cite at least one expected chunk; the mean share of expected chunks cited is 0.85.
This matches retrieval hit@5 with reranking, because the stub cites every retrieved chunk.
One run used 66 embedding tokens and 5 rerank requests.

## HTTP API (M5)

**Local demo only. There is no authentication, so it is not for production.** The server
listens on `127.0.0.1:8000` only. It wraps the same `answer_question()` as `scripts/ask.py`.

| Endpoint | What it does |
|---|---|
| `POST /ask` | `{question, top_k}` -> `{answer, citations[{chunk_id, file, product, section, page, chunk_type}], generator, disclaimer}` |
| `GET /health` | Liveness and the provider names. It calls no external service. |
| `GET /docs` | Swagger UI. "Try it out" on `/ask` starts with an example question. |

Settings for the demo, in `.env` (see `.env.example`):

| Variable | Demo value | Notes |
|---|---|---|
| `EMBEDDER` | `pinecone` | must match the index (one index, one embedder) |
| `VECTOR_STORE` | `pinecone` | |
| `RERANKER` | `pinecone` | one rerank request per `/ask` (free plan: 500 per month) |
| `GENERATOR` | `stub` | no generative model; swapped by this variable alone (`anthropic` also needs `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`) |
| `PINECONE_NAMESPACE` | `__default__` | required, no default in code; `__default__` is the default namespace (the M3 data) |

The Pinecone settings from "Index and search with Pinecone" are also needed:
`PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_EMBED_MODEL`, `PINECONE_RERANK_MODEL`.
Providers are built once at startup, so a missing setting stops the server with the variable's
name instead of failing on the first request.

```
uv run --env-file .env python -m src.api      # http://127.0.0.1:8000/docs
```

Demo steps:

1. Open `http://127.0.0.1:8000/health` and check that `embedder`, `vector_store` and
   `reranker` are `pinecone` and `generator` is `stub`. The startup log line shows the same
   names.
2. Open `http://127.0.0.1:8000/docs`, choose `POST /ask`, then "Try it out" and "Execute" with
   the example question "What are the excipients of Cablivi?".
3. The answer lists the retrieved passages with their citations (product, section, page,
   chunk ID) and the disclaimer.

Input and errors:

- `question` is 1 to 1000 characters after trimming spaces, and `top_k` is 1 to 20 (default 5).
  Anything else returns `422`. FastAPI's 422 body repeats the invalid input to the caller.
- If an external service fails, `/ask` returns `502` with a fixed message and a `request_id`.
  The response has no exception text, no key, and no index name. The server log has the same
  `request_id` and the error's class name only.
- Logs are JSON lines, the same format as the Lambda logs: one line per request with
  `request_id`, `method`, `path`, `status_code` and `duration_ms`. The question, the request
  body, query strings and headers are never logged. Every response has an `X-Request-ID` header.

OpenAPI: `docs/openapi.json` is generated from the code and committed. CI checks that it is up
to date. After changing the API or upgrading FastAPI or Pydantic, regenerate it:

```
uv run python -m scripts.export_openapi           # write docs/openapi.json
uv run python -m scripts.export_openapi --check   # what CI runs
```

Docker (local only; the image is never pushed to a registry):

```
docker build -t doc-rag-api .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env doc-rag-api
```

Inside the container the server listens on `0.0.0.0`, which port publishing needs.
`-p 127.0.0.1:8000:8000` publishes it on the host's loopback only. `.dockerignore` is an
allow-list (`pyproject.toml`, `uv.lock`, `.python-version`, `src/`), so `.env` is never copied
into the image. Settings come from `--env-file` at run time, so the Pinecone key is in the
container's environment while it runs. This is fine for a local demo only. Docker's
`--env-file` does not remove quotes, so write values in `.env` without quotes. The image
installs only the locked runtime dependencies (no dev tools) and runs as a non-root user.
Startup took 20 to 40 seconds in the container (a few seconds outside Docker). Python imports
take 1.6 s, so most of the time is spent building the Pinecone clients. The cause has not
been investigated.

## Event-driven pipeline on AWS (M6)

```
PDF -> s3://$S3_BUCKET/incoming/
  -> EventBridge rule (Object Created, this bucket, prefix incoming/)
  -> Step Functions (Standard)
       RegisterDocument   sha256 of the PDF, DynamoDB status RECEIVED
       CacheHit?          textract-cache/<sha256>.json exists -> skip Textract
       StartExtraction -> Wait 10 s -> CheckExtraction -> (IN_PROGRESS: back to Wait)
       SaveExtraction     merged Textract JSON -> textract-cache/
       IndexDocument      chunk -> embed -> Pinecone namespace "pipeline"
       MarkIndexed        DynamoDB status INDEXED, page_count, chunk_count
       any failure        -> MarkFailed: DynamoDB status FAILED, error, cause
```

States, retries and failure handling are in `infra/statemachine.asl.json`. All the AWS
resources are in `infra/` (Terraform, local state). Transient errors are retried (3 attempts
in total, waiting 2 s and then 4 s). Other errors, such as a failed Textract job, go to
`FAILED` without a retry. Only IDs and counts pass between states (the limit is 256 KB). The
Textract result itself goes through the S3 cache. The pipeline writes to the Pinecone namespace
`pipeline`, so the M3 data in the default namespace is left untouched. The Lambda functions run
Python 3.12 without a VPC. All five share one zip, and each step has its own least-privilege
role. The Pinecone API key is read from Secrets Manager. Terraform creates only the empty
secret, so the key is never in tfvars, in the Terraform state, or in git.

### Deploy

Needs Terraform >= 1.16 and an AWS user that is allowed to manage `doc-rag-mock-*` resources.
`infra/deployer-policy.json` is the policy used here. It is too long for an inline user policy
(the limit is 2,048 characters), so attach it as a customer managed policy.

```
# 1. The bucket's notification configuration must be empty: Terraform replaces all of it.
uv run --env-file .env -- bash -c 'aws s3api get-bucket-notification-configuration --bucket "$S3_BUCKET"'

# 2. Build the Lambda zip (build/lambda.zip) and plan. Values come from .env; none has a default.
scripts/build_lambda.sh
uv run --env-file .env -- bash -c 'TF_VAR_bucket_name="$S3_BUCKET" TF_VAR_pinecone_index="$PINECONE_INDEX" \
  TF_VAR_pinecone_embed_model="$PINECONE_EMBED_MODEL" TF_VAR_pinecone_namespace=pipeline \
  terraform -chdir=infra plan -out=m6.tfplan'
terraform -chdir=infra apply m6.tfplan

# 3. Put the Pinecone key into the secret (typed, not echoed, not kept in shell history).
read -s PINECONE_KEY && aws secretsmanager put-secret-value \
  --secret-id doc-rag-mock/pinecone-api-key --secret-string "$PINECONE_KEY"; unset PINECONE_KEY
```

### Run

```
uv run --env-file .env -- bash -c 'aws s3 cp data/pdfs/<file>.pdf "s3://$S3_BUCKET/incoming/"'
aws dynamodb scan --table-name doc-rag-mock-documents \
  --projection-expression "doc_id, #s, chunk_count, #e" \
  --expression-attribute-names '{"#s":"status","#e":"error"}'
```

To test retries and `FAILED`, add `TF_VAR_force_fail_step=index` to the plan command and apply.
The index step then raises a transient error on every attempt. Plan again without it to turn it
off.

### Cost

On the cache-hit path Textract is not called. On the cache-miss path, Textract LAYOUT costs about
0.004 USD per page (the 3-page run cost about 0.012 USD). Lambda, Step Functions, DynamoDB
and EventBridge stayed within the free tier at this volume. The secret costs 0.40 USD per month,
billed pro rata. Embeddings use the Pinecone free plan (one 39-page document is about 35,000
tokens).

### Measured (2026-10-19, cold starts)

| Run | Execution | Lambda details |
|---|---|---|
| Cablivi SmPC, 39 pages, cache hit | 8 s | RegisterDocument 1.9 s (116 of 256 MB); IndexDocument, 138 chunks, 3.9 s (158 of 1024 MB) |
| Cablivi medicine overview, 3 pages, cache miss | 27 s | Textract finished within the first 10 s wait; StartExtraction and CheckExtraction used 104 of 128 MB (since raised to 256 MB); SaveExtraction used 116 of 1024 MB |

### Known limitations

- The product name comes only from EMA file names (`<product>-epar-product-information...`).
  For any other name it is empty and is not guessed. Chunks from such files (for example the
  "medicine overview" PDF) are embedded without the product name, which can lower retrieval.
- Errors raised by the Pinecone client are not classified as transient, so for example a
  Pinecone 5xx makes the document `FAILED` at once instead of being retried.
- If RegisterDocument fails, the run has no `doc_id` yet (the PDF was not hashed), so the
  failure is only in the Step Functions execution, not in DynamoDB.
- Two uploads of the same PDF at the same time are not serialized. Both runs write the same
  chunk IDs, so the result is the same, but the status may flip between them.
- The IN_PROGRESS loop back to Wait is covered only by unit tests. In the real runs Textract
  always finished within the first wait.
- Object keys are passed on as EventBridge delivers them. Only plain file names (no spaces) have
  been tested.
- The handlers' JSON log lines have no timestamp and no Lambda request ID of their own (the
  runtime's lines have both). Sort by CloudWatch's `@timestamp`, and use `execution_arn` and
  `step` to follow one run. `status` in the logs is the step's status (`STARTED`,
  `SUCCEEDED`, `FAILED`). The document status (`INDEXED`) is only in DynamoDB, because
  MarkIndexed writes it from Step Functions without a Lambda.
- EventBridge has no dead-letter queue. A failed start shows only in the rule's
  `FailedInvocations` metric.
- In answers, the same ingredient list from the labelling section (for example
  "3. LIST OF EXCIPIENTS" on several pack labels) can fill the top places. Near-duplicate
  passages are not removed yet.

### Clean up

```
uv run --env-file .env -- scripts/cleanup.sh
```

It asks before each step. The steps are: delete the Pinecone namespace `pipeline`, delete the
objects under `incoming/`, then run `terraform destroy`, which also removes the DynamoDB table
and the bucket's EventBridge notification. `raw/` and `textract-cache/` are kept. At the end
it prints the manual root steps for removing the deployer policy from the `rag-mock` user.

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
# .env needs PINECONE_API_KEY, PINECONE_INDEX, PINECONE_EMBED_MODEL
# and, for --rerank, PINECONE_RERANK_MODEL (no defaults in code)
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
