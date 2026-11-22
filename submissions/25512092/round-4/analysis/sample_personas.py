#!/usr/bin/env python3
"""Sample about 20,000 rows of nvidia/Nemotron-Personas-Korea (CC BY 4.0) without downloading the 2 GB of parquet.

    python analysis/sample_personas.py [--windows 200] [--seed 7]

Uses the Hugging Face dataset viewer rows API (datasets-server.huggingface.co/rows, at most 100 rows a call) at random
offsets across all 1,000,000 rows: a sample of 200 windows of 100 rows, spread over the whole dataset (the market's
own persona-pool.py picks random row groups the same way). Writes analysis/data/personas_sample.jsonl (gitignored).
Standard library only.
"""
import argparse
import json
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://datasets-server.huggingface.co/rows"
DATASET = "nvidia/Nemotron-Personas-Korea"
TOTAL = 1_000_000
OUT = Path(__file__).resolve().parent / "data" / "personas_sample.jsonl"


def rows(offset, length=100, tries=5):
    q = urllib.parse.urlencode({"dataset": DATASET, "config": "default", "split": "train", "offset": offset, "length": length})
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{API}?{q}", headers={"user-agent": "persona-sample-script"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return [x["row"] for x in json.load(r)["rows"]]
        except Exception as e:                           # 429 or a slow page: back off and retry
            wait = 2 ** i + random.random()
            print(f"  offset {offset}: {type(e).__name__} {e}; retry in {wait:.0f} s", flush=True)
            time.sleep(wait)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    offsets = sorted(rnd.sample(range(0, TOTAL - 100, 100), a.windows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with OUT.open("w", encoding="utf-8") as f:
        for i, off in enumerate(offsets):
            got = rows(off)
            for r in got:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += len(got)
            if i % 20 == 0:
                print(f"{i + 1}/{len(offsets)} windows, {n} rows", flush=True)
            time.sleep(0.3)
    print(f"{OUT}: {n} rows from {len(offsets)} windows")


if __name__ == "__main__":
    main()
