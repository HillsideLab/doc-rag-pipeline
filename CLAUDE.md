# CLAUDE.md

Project: doc-rag-pipeline. Read SPEC.md first; it is the source of truth.

## How to work

- Start in plan mode. Before each milestone (M0 to M7 in SPEC.md), show a short plan and wait for approval. Build one milestone at a time. Do not jump ahead to Tier 2/3 until Tier 1 works.
- Keep it small and explainable. The owner must be able to explain every file and every design choice in English in an interview. Prefer simple, readable code over clever abstractions. When you add a file, add one line about its purpose to `docs/ARCHITECTURE.md` (written in Japanese).
- Python 3.12 via `uv`. FastAPI, Pydantic v2, pytest, ruff. Type hints everywhere.
- Business logic lives in plain modules under `src/`. Lambda handlers are thin wrappers.

## Hard rules (never break)

- Never read, print, log, or commit AWS credentials, `~/.aws/*`, `.env`, API keys, or tokens. Never ask the user to paste secrets. Use the AWS profile name `rag-mock` and `AWS_REGION` only.
- Never hard-code the region or the account ID. Read `AWS_REGION` (default `us-east-1`).
- Ask before any command that creates, changes, or deletes cloud resources: `terraform apply`, `terraform destroy`, `aws ... create/put/delete`, bucket or table changes. `terraform plan` and read-only `aws ... list/describe/get` are fine.
- Do NOT use or create: OpenSearch Serverless, Bedrock Knowledge Bases quick-create, NAT Gateway, VPC for Lambda, provisioned throughput, GPU or Batch resources, SageMaker endpoints.
- Cost: stay under about 10 USD. Cache Textract results in S3 and never re-run extraction on an already processed PDF. Use the cheapest model for development. Tell the user before any step that could cost more than 1 USD.
- Public documents only. Never add real company data or proprietary code. Do not commit PDFs; list download links in the README.
- Tests must not call real AWS, Pinecone, or any network service. Use the fakes. Real calls are opt-in with `@pytest.mark.integration`.
- Be honest in the README. Mark a component "verified" only after a real call has succeeded. Bedrock is currently blocked by an account restriction; do not claim it works until it does.
- No emojis in code or docs. Keep the README in English.

## Model-provider rule

All model/vector/extraction calls go through the interfaces in SPEC.md section 5. Defaults must work offline with fakes. Bedrock Claude must be called with an inference profile ID (list them with `aws bedrock list-inference-profiles`), not a bare model ID. Titan embeddings use `amazon.titan-embed-text-v2:0` with dimension 1024. One index uses one embedder only.

## Commands

- Setup: `uv sync`
- Test: `uv run pytest` (unit only) / `uv run pytest -m integration` (real services, opt-in)
- Lint: `uv run ruff check . && uv run ruff format --check .`
- API: `uv run uvicorn src.api.main:app --reload`
- Terraform: `cd infra && terraform fmt -check && terraform validate`

## Git

- Small commits with clear messages. Never force-push. `.gitignore` must cover `.env`, `.venv`, `*.pdf`, `out.json`, `*.tfstate*`, `.terraform/`.
