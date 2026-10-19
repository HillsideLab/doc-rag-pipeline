#!/usr/bin/env bash
# Remove what the M6 pipeline created. Every step asks first and can be skipped.
#
#   1. Pinecone namespace "pipeline" (the M3 data in the default namespace is kept)
#   2. Objects under s3://$S3_BUCKET/incoming/ (raw/ and textract-cache/ are kept, so a later
#      run does not pay for Textract again; the bucket itself is not managed by Terraform)
#   3. terraform destroy: Lambda, Step Functions, EventBridge rule, DynamoDB table (with its
#      items), IAM roles, log groups, the secret, and the bucket's EventBridge notification
#   4. Prints the manual root steps for the deployer policy (must come after step 3)
#
# Usage (from the repo root):
#   uv run --env-file .env -- scripts/cleanup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

NAMESPACE=pipeline

for name in AWS_PROFILE AWS_REGION S3_BUCKET PINECONE_INDEX PINECONE_EMBED_MODEL; do
  if [ -z "${!name:-}" ]; then
    echo "$name is not set. Run: uv run --env-file .env -- scripts/cleanup.sh" >&2
    exit 1
  fi
done

confirm() {
  local answer
  read -r -p "$1 [y/N] " answer
  [ "$answer" = "y" ]
}

echo "== 1. Pinecone namespace '$NAMESPACE' in index $PINECONE_INDEX"
uv run python - "$NAMESPACE" <<'EOF'
import os, sys
from pinecone import Pinecone
namespaces = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(
    name=os.environ["PINECONE_INDEX"]).describe_index_stats().namespaces
print("records:", namespaces[sys.argv[1]].vector_count if sys.argv[1] in namespaces else 0)
EOF
if confirm "Delete every record in namespace '$NAMESPACE'?"; then
  uv run python - "$NAMESPACE" <<'EOF'
import os, sys
from pinecone import Pinecone
index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(name=os.environ["PINECONE_INDEX"])
index.delete(delete_all=True, namespace=sys.argv[1])
print("deleted namespace", sys.argv[1])
EOF
else
  echo "skipped"
fi

echo "== 2. Objects under s3://$S3_BUCKET/incoming/"
aws s3 ls "s3://$S3_BUCKET/incoming/" || true
if confirm "Delete these objects?"; then
  aws s3 rm "s3://$S3_BUCKET/incoming/" --recursive
else
  echo "skipped"
fi

echo "== 3. terraform destroy (Terraform shows the plan and asks again)"
if confirm "Run terraform destroy?"; then
  TF_VAR_bucket_name="$S3_BUCKET" \
    TF_VAR_pinecone_index="$PINECONE_INDEX" \
    TF_VAR_pinecone_embed_model="$PINECONE_EMBED_MODEL" \
    TF_VAR_pinecone_namespace="$NAMESPACE" \
    PINECONE_API_KEY="" \
    terraform -chdir=infra destroy
else
  echo "skipped"
fi

cat <<'EOF'
== 4. Manual step (signed in as root, after terraform destroy has finished)
The rag-mock user still has the policy used by Terraform. Remove it when nothing is left:
  IAM console > Users > rag-mock > Permissions > doc-rag-mock-terraform-deployer > Remove
  IAM console > Policies > doc-rag-mock-terraform-deployer > Delete
or with the AWS CLI as root:
  aws iam detach-user-policy --user-name rag-mock --policy-arn arn:aws:iam::<account-id>:policy/doc-rag-mock-terraform-deployer
  aws iam delete-policy --policy-arn arn:aws:iam::<account-id>:policy/doc-rag-mock-terraform-deployer
Without this policy, rag-mock can no longer run terraform apply or destroy for this project.
EOF
