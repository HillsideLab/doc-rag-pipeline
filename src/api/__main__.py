"""Run the API locally: uv run --env-file .env python -m src.api [--host 127.0.0.1]

Listens on 127.0.0.1 only, since there is no authentication. The Docker image passes
--host 0.0.0.0 inside the container and is published on the host's 127.0.0.1 only.
"""

import argparse

import uvicorn

from src.pipeline import logging_json

PORT = 8000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    logging_json.configure()
    # log_config=None: uvicorn keeps the JSON handler; access_log=False: our middleware logs
    # each request without the query string.
    uvicorn.run("src.api.main:app", host=args.host, port=PORT, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
