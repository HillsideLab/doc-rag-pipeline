#!/usr/bin/env bash
# Build build/lambda.zip for the M6 Lambda functions: src/ plus its runtime dependencies,
# as Linux x86_64 wheels for Python 3.12 (the Lambda runtime). One zip serves all five
# functions; only the handler name differs.
#
# Left out: boto3 and its dependencies (the Lambda runtime provides them) and numpy (only
# used by the offline fakes). The zip is built with fixed timestamps and sorted entries, so
# the same sources give the same zip and Terraform sees no change.
#
# Usage (from the repo root): scripts/build_lambda.sh
set -euo pipefail
cd "$(dirname "$0")/.."

BUILD=build/lambda
ZIP=build/lambda.zip
rm -rf "$BUILD" "$ZIP"
mkdir -p "$BUILD"

uv export --frozen --no-dev --no-hashes --no-emit-project \
  --no-emit-package boto3 --no-emit-package botocore --no-emit-package s3transfer \
  --no-emit-package jmespath --no-emit-package python-dateutil --no-emit-package six \
  --no-emit-package urllib3 --no-emit-package numpy \
  > build/requirements.txt

uv pip install --quiet --target "$BUILD" --requirement build/requirements.txt \
  --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:

cp -R src "$BUILD/src"
find "$BUILD" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$BUILD" -exec touch -t 198001010000 {} +
(cd "$BUILD" && find . -type f | LC_ALL=C sort | zip -q -X "../lambda.zip" -@)

echo "built $ZIP ($(wc -c < "$ZIP" | tr -d ' ') bytes)"
