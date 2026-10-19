"""Write the API's OpenAPI document to docs/openapi.json, or check that it is up to date.

Usage (from the repo root):
    uv run python -m scripts.export_openapi           # write docs/openapi.json
    uv run python -m scripts.export_openapi --check   # exit 1 if it differs from the code (CI)

Needs no .env and no network: importing the app does not build any provider.
"""

import argparse
import json
import sys
from pathlib import Path

from src.api.main import app

OUTPUT = Path("docs/openapi.json")


def render() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()

    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != expected:
            print(f"{OUTPUT} is out of date. Run: uv run python -m scripts.export_openapi")
            return 1
        print(f"{OUTPUT} is up to date")
        return 0
    OUTPUT.write_text(expected)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
