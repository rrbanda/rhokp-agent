"""CLI entry point: python -m rhokp 'your query'

Supports optional flags for filtering by product, version, and document kind.
"""

import argparse
import json
import logging
import sys

from rhokp.client import retrieve
from rhokp.logging import bind_request_id, configure_logging
from rhokp.models import OKPError


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rhokp",
        description="Search Red Hat Offline Knowledge Portal (OKP)",
    )
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--rows", type=int, default=None, help="Max documents to return")
    parser.add_argument("--product", type=str, default=None, help="Filter by product name")
    parser.add_argument("--version", type=str, default=None, help="Filter by doc version")
    parser.add_argument("--kind", type=str, default=None, help="Filter by document kind")
    parser.add_argument("--context-only", action="store_true", help="Print only the LLM context")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG-level logging to stderr"
    )
    parser.add_argument(
        "--json-log", action="store_true", help="Emit JSON log lines (default: text)"
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(level=level, json_format=args.json_log)
    bind_request_id()

    query = " ".join(args.query)

    try:
        result = retrieve(
            query,
            rows=args.rows,
            product=args.product,
            version=args.version,
            document_kind=args.kind,
        )
    except (OKPError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.context_only:
        print(result.context)
    else:
        print(json.dumps(result.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()
