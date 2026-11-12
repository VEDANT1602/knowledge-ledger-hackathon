"""Measure first answers and repeated answers with the organizer kit kept local."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path


def summary(times):
    ordered = sorted(times)
    if not ordered:
        return {"questions": 0}
    return {
        "questions": len(times),
        "p50_ms": round(statistics.median(ordered) * 1000, 4),
        "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] * 1000, 4),
        "max_ms": round(max(ordered) * 1000, 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--submission", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    harness = args.kit.resolve() / "harness"
    sys.path.insert(0, str(harness))
    spec = importlib.util.spec_from_file_location("organizer_runner", harness / "run_eval.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    ks = runner.load_submission(args.submission.resolve())
    snapshots = runner.load_snapshots(args.kit.resolve() / "snapshots")
    started = time.perf_counter()
    for snapshot in snapshots:
        ks.ingest(snapshot)
    ingest_seconds = time.perf_counter() - started
    items = [json.loads(line) for line in (args.kit / "eval" / "public_eval.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    seen = set()
    queries = []
    for item in items:
        key = (item["question"], item.get("as_of"))
        if key not in seen:
            seen.add(key)
            queries.append(key)
    first, repeat, answers = [], [], []
    for question, as_of in queries:
        started = time.perf_counter()
        answer = ks.answer(question, as_of=as_of)
        first.append(time.perf_counter() - started)
        answers.append(answer.text)
    stable = True
    for (question, as_of), earlier in zip(queries, answers):
        started = time.perf_counter()
        answer = ks.answer(question, as_of=as_of)
        repeat.append(time.perf_counter() - started)
        stable = stable and earlier == answer.text
    print(json.dumps({
        "python": sys.version.split()[0],
        "ingest_seconds": round(ingest_seconds, 4),
        "first_pass_empty_answer_cache": summary(first),
        "repeat_pass_same_queries": summary(repeat),
        "repeat_text_identical": stable,
    }, indent=2))


if __name__ == "__main__":
    main()
