"""Thin CLI surface. The UI (app.py) is the primary surface; this exists so the
same engine is scriptable and easy to drive from tests and the demo.

    python -m transformer --inputs samples --out out/default_output.json
    python -m transformer --inputs samples --config samples/configs/custom.json \
        --out out/custom_output.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .pipeline import run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Multi-source candidate data transformer")
    parser.add_argument("--inputs", required=True, help="directory of input sources")
    parser.add_argument("--config", help="path to a custom output config JSON (optional)")
    parser.add_argument("--out", help="write result JSON here (otherwise stdout)")
    parser.add_argument("--no-github", action="store_true", help="skip the live GitHub fetch")
    parser.add_argument("--report", help="write the trust report (quality + explain + review queue) here")
    parser.add_argument("--review-threshold", type=float, default=0.6,
                        help="confidence below which a candidate is flagged for review (default 0.6)")
    args = parser.parse_args(argv)

    config = None
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            config = json.load(fh)

    result = run(args.inputs, config, fetch_github=not args.no_github,
                 trust=bool(args.report), review_threshold=args.review_threshold)
    payload = json.dumps(result["profiles"], indent=2, ensure_ascii=False)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
        print(f"wrote {len(result['profiles'])} profile(s) to {args.out}", file=sys.stderr)
    else:
        print(payload)

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result["trust"], indent=2, ensure_ascii=False) + "\n")
        b = result["trust"]["batch"]
        print(
            f"trust report -> {args.report} | {b['accepted']} accepted, "
            f"{b['needs_review']} need review (avg confidence {b['avg_confidence']}, "
            f"avg completeness {b['avg_completeness']})",
            file=sys.stderr,
        )

    if result["errors"]:
        print(f"{len(result['errors'])} candidate(s) had errors:", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e['candidate_id']}: {e['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
