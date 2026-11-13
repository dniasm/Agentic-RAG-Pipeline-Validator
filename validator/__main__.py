"""Command line.

    python -m validator status            corpus, question set and progress of each case
    python -m validator plan              chunks (= embedding requests) still to ingest
    python -m validator ingest            ingest new or changed corpus files
    python -m validator validate          check questions.json / expected.json
    python -m validator run case2         run a case until done (Ctrl+C stops; rerun to resume)
    python -m validator run case2 --limit 3     smoke test on the first 3 questions
    python -m validator metrics [case1]   compute metrics (all cases if none given)

Don't run this while the portal's server is running: they share the embedded vector store.
"""
import argparse
import json
import logging
import sys

from validator import corpus, metrics, runner, store
from validator.rag import vectorstore
from validator.config import CASES, quiet_noisy_loggers


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    quiet_noisy_loggers()
    p = argparse.ArgumentParser(prog="python -m validator")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("plan")
    sub.add_parser("ingest")
    sub.add_parser("validate")
    r = sub.add_parser("run")
    r.add_argument("case", choices=sorted(CASES))
    r.add_argument("--limit", type=int, default=None)
    m = sub.add_parser("metrics")
    m.add_argument("case", nargs="?", choices=sorted(CASES))
    args = p.parse_args()

    if args.cmd == "status":
        s = corpus.status()
        print(json.dumps({"corpus": s, "questions": len(store.questions()),
                          "problems": store.validate_question_set(),
                          "cases": {k: {n: len(store.load(k, n)) for n in ("generated", "judge_small", "judge_large",
                                                                           "human")} for k in CASES}}, indent=2))
    elif args.cmd == "plan":
        print(json.dumps(corpus.plan(), indent=2))
    elif args.cmd == "ingest":
        print(json.dumps(corpus.ingest(progress=print), indent=2))
    elif args.cmd == "validate":
        problems = store.validate_question_set()
        print("\n".join(problems) if problems else f"OK: {len(store.questions())} questions, all with rubrics")
        return 1 if problems else 0
    elif args.cmd == "run":
        run = runner.start(args.case, args.limit)
        try:
            run.wait()
        except KeyboardInterrupt:
            run.stop()
            run.wait()
        print(json.dumps({k: v.view() for k, v in run.lanes.items()}, indent=2))
    elif args.cmd == "metrics":
        out = metrics.compute(args.case) if args.case else metrics.compare_cases()
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        vectorstore.close_client()
    sys.exit(code)
