"""Quick latency benchmark: N sequential chat turns against the running API.

Uses the golden questions (knowledge questions, no actions to approve), each in a new
conversation. Reports p50 / p95 end-to-end latency and errors. Nebius latency varies a
lot over the day, so record the time of the run together with the numbers.

Usage: uv run python scripts/bench.py [--n 10]
"""

import argparse
import json
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def main(n: int) -> None:
    golden = [
        json.loads(line) for line in Path("tests/fixtures/golden.jsonl").read_text().splitlines()
    ]
    questions = [golden[i % len(golden)]["question"] for i in range(n)]
    latencies, errors = [], 0
    print(f"Benchmark started {datetime.now():%Y-%m-%d %H:%M} · {n} turns")
    for i, question in enumerate(questions, 1):
        start = time.perf_counter()
        try:
            r = httpx.post(
                f"{API}/chat",
                json={"message": question, "thread_id": f"bench-{uuid.uuid4().hex[:8]}"},
                timeout=300,
            )
            r.raise_for_status()
            ok = r.json()["status"] == "done"
        except httpx.HTTPError:
            ok = False
        elapsed = time.perf_counter() - start
        errors += not ok
        latencies.append(elapsed)
        print(f"{i:>2}. {elapsed:6.1f} s  {'ok ' if ok else 'ERR'}  {question}")
    print(
        f"\np50 = {statistics.median(latencies):.1f} s · p95 = {percentile(latencies, 95):.1f} s"
        f" · min = {min(latencies):.1f} s · max = {max(latencies):.1f} s · errors = {errors}/{n}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10)
    main(parser.parse_args().n)
