"""Run Textract on one local PDF (using the S3 cache) and save the ExtractedDocument.

Usage (from the repo root):
    uv run --env-file .env python -m scripts.extract_pdf data/pdfs/<file>.pdf [--yes]

Needs AWS_PROFILE, AWS_REGION and S3_BUCKET in the environment. Asks before any step
that costs money (a cache miss starts a Textract job). Output: data/extracted/<doc_id>.json
"""

import argparse
import hashlib
import logging
import sys
from pathlib import Path

from src.chunking import chunk_document
from src.providers.textract import LAYOUT_USD_PER_PAGE, TextractExtractor

OUT_DIR = Path("data/extracted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="local PDF file")
    parser.add_argument("--yes", action="store_true", help="do not ask before running Textract")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    pdf: Path = args.pdf
    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    extractor = TextractExtractor.from_env()

    cache_hit = extractor.has_cache(sha256)
    if cache_hit:
        print(f"cache hit for {pdf.name}: Textract will not run (no cost)")
    else:
        print(f"cache miss for {pdf.name}: Textract LAYOUT will run")
        print(f"approximate cost: {LAYOUT_USD_PER_PAGE} USD per page")
        if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
            print("aborted")
            return 1

    key = extractor.upload(pdf)
    doc = extractor.extract(key)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{doc.doc_id}.json"
    out.write_text(doc.model_dump_json(indent=2))

    pages = len(doc.pages)
    lines = sum(len(page.lines) for page in doc.pages)
    headings = sum(line.is_heading for page in doc.pages for line in page.lines)
    print(f"s3 key:   {key}")
    print(f"doc_id:   {doc.doc_id}")
    print(f"pages:    {pages}")
    print(f"lines:    {lines}")
    print(f"headings: {headings}")
    print(f"chunks:   {len(chunk_document(doc))}")
    if not cache_hit:
        print(f"approximate Textract cost: {pages * LAYOUT_USD_PER_PAGE:.3f} USD")
    print(f"saved:    {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
