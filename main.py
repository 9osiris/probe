import argparse
import json
import os
import sys

from client import ChatClient
from evals import load_evals
from runner import run_evals


def main():
    p = argparse.ArgumentParser(description="score a model on benchmark prompts")
    p.add_argument("--model", default=os.environ.get("PROBE_MODEL", "gpt-4o-mini"))
    p.add_argument("--base-url", default=os.environ.get("PROBE_BASE_URL", "https://api.openai.com/v1"))
    p.add_argument("--api-key", default=os.environ.get("PROBE_API_KEY", os.environ.get("OPENAI_API_KEY", "")))
    p.add_argument("--evals", default="example_evals.json")
    p.add_argument("--timeout", type=float,
                   default=float(os.environ.get("PROBE_TIMEOUT", "120")),
                   help="seconds per api request (default 120)")
    p.add_argument("--jobs", type=int, default=1,
                   help="evals to run in parallel (default 1)")
    p.add_argument("--json", action="store_true",
                   help="print machine-readable json instead of the table")
    p.add_argument("--filter", default=None, metavar="TEXT",
                   help="only run evals whose name contains TEXT (case-insensitive)")
    p.add_argument("--show", action="store_true",
                   help="print the reply under each failing eval in table mode")
    p.add_argument("--fail-fast", action="store_true",
                   help="stop after the first failure, the rest show as skipped (runs serially)")
    args = p.parse_args()

    if args.jobs < 1:
        p.error("--jobs must be at least 1")
    if args.timeout <= 0:
        p.error("--timeout must be positive")

    try:
        evals = load_evals(args.evals)
    except (ValueError, OSError) as e:
        print("probe: %s" % e, file=sys.stderr)
        return 2

    if args.filter is not None:
        needle = args.filter.lower()
        evals = [ev for ev in evals if needle in ev["name"].lower()]
        if not evals:
            print("probe: no evals matched filter %r" % args.filter, file=sys.stderr)
            return 2

    client = ChatClient(args.base_url, args.api_key, args.model, timeout=args.timeout)
    results = run_evals(evals, client, jobs=args.jobs, fail_fast=args.fail_fast)
    passed = sum(1 for r in results if r["passed"])
    skipped = sum(1 for r in results if r.get("skipped"))

    if args.json:
        out = {
            "model": args.model,
            "passed": passed,
            "total": len(results),
            "results": [
                {
                    "name": r["name"],
                    "passed": r["passed"],
                    "ms": r["ms"],
                    **({"skipped": True} if r.get("skipped") else {}),
                    **({"reply": r["reply"]} if "reply" in r else {}),
                    **({"error": r["error"]} if "error" in r else {}),
                }
                for r in results
            ],
        }
        print(json.dumps(out, indent=2))
        return 0 if passed == len(results) else 1

    width = max(len(r["name"]) for r in results)
    for r in results:
        status = "SKIP" if r.get("skipped") else ("PASS" if r["passed"] else "FAIL")
        print("%-*s  %s" % (width, r["name"], status))
        if not r["passed"] and "error" in r:
            print("    error: %s" % r["error"])
        if args.show and not r["passed"] and "reply" in r:
            print("    reply: %s" % r["reply"])

    if skipped:
        print("%d/%d passed (%d skipped)" % (passed, len(results), skipped))
    else:
        print("%d/%d passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
