#!/usr/bin/env python3
"""Retrieval evaluation against a live OKP instance.

Computes Precision@5 and Mean Reciprocal Rank (MRR) over the query set
in ``queries.jsonl``.

Usage:
    # Requires a running RHOKP instance (set RHOKP_BASE_URL if not default)
    python eval/run_eval.py

    # With custom rows count
    python eval/run_eval.py --rows 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rhokp import OKPClient, OKPConfig, OKPError


def load_queries(path: Path) -> list[dict]:
    queries = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def precision_at_k(relevant_kinds: list[str], result_kinds: list[str], k: int = 5) -> float:
    """Fraction of top-k results whose document_kind is in the expected set."""
    if not relevant_kinds:
        return 1.0
    top_k = result_kinds[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for kind in top_k if kind in relevant_kinds)
    return hits / len(top_k)


def reciprocal_rank(relevant_kinds: list[str], result_kinds: list[str]) -> float:
    """1 / rank of the first result whose document_kind is in the expected set."""
    if not relevant_kinds:
        return 1.0
    for i, kind in enumerate(result_kinds):
        if kind in relevant_kinds:
            return 1.0 / (i + 1)
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument("--rows", type=int, default=5, help="Number of docs to retrieve")
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path(__file__).parent / "queries.jsonl",
        help="Path to queries JSONL file",
    )
    args = parser.parse_args()

    queries = load_queries(args.queries)
    if not queries:
        print("No queries found in", args.queries)
        sys.exit(1)

    config = OKPConfig.from_env(rows=args.rows)
    precisions: list[float] = []
    rrs: list[float] = []

    print(f"Evaluating {len(queries)} queries against {config.base_url} (rows={args.rows})")
    print("-" * 72)

    with OKPClient(config) as client:
        for i, entry in enumerate(queries, 1):
            query = entry["query"]
            expected_kinds = entry.get("expected_kinds", [])

            try:
                result = client.retrieve(query, rows=args.rows)
                result_kinds = [doc.document_kind for doc in result.docs]
                p = precision_at_k(expected_kinds, result_kinds, k=args.rows)
                rr = reciprocal_rank(expected_kinds, result_kinds)
            except OKPError as exc:
                print(f"  [{i:2d}] ERROR: {query[:60]}: {exc}")
                p = 0.0
                rr = 0.0

            precisions.append(p)
            rrs.append(rr)
            status = "OK" if p > 0 else "MISS"
            print(
                f"  [{i:2d}] {status:4s}  P@{args.rows}={p:.2f}  RR={rr:.2f}  "
                f"found={result.num_found:5d}  {query[:55]}"
            )

    avg_p = sum(precisions) / len(precisions) if precisions else 0.0
    mrr = sum(rrs) / len(rrs) if rrs else 0.0

    print("-" * 72)
    print(f"  Precision@{args.rows}: {avg_p:.3f}")
    print(f"  MRR:          {mrr:.3f}")
    print(f"  Queries:      {len(queries)}")


if __name__ == "__main__":
    main()
