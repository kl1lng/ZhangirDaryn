"""Extract MediaPipe hands + body pose + face from the chosen Slovo videos into a SEPARATE motion database.

Slovo is a Russian Sign Language (RSL) dataset, CC BY-SA 4.0 variant (see data/slovo/license_en_us.pdf).
Nothing here touches data/motion_library.sqlite3 or the public PWA database.

  .venv-pwa\Scripts\python.exe scripts/slovo_extract.py [--limit N] [--words word1,word2] [--db PATH]
Candidates come from data/slovo/candidates.json (3 per word); every candidate is imported so the best one can be
chosen after extraction by hand coverage. Safe to re-run: clips for an already imported video are skipped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

SOURCE = "Slovo RSL dataset (SaluteDevices), github.com/ai-forever/slovo"
LICENSE = "Public license with attribution and conditions reserved (CC BY-SA 4.0 variant)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--words", default="")
    parser.add_argument("--rank", type=int, default=3, help="use the first N candidates per word (best first)")
    parser.add_argument("--shard", default="0/1", help="i/n: process every n-th job into its own database file")
    parser.add_argument("--db", default="")
    args = parser.parse_args()

    from src.motion_db import import_video_motion

    videos = ROOT / "data" / "slovo" / "videos"
    candidates = json.loads((ROOT / "data" / "slovo" / "candidates.json").read_text(encoding="utf-8"))
    wanted = {w.strip() for w in args.words.split(",") if w.strip()}
    shard, shards = (int(x) for x in args.shard.split("/"))
    suffix = "" if shards == 1 else f"_{shard}"
    db = args.db or str(ROOT / "data" / "slovo" / f"motion_slovo{suffix}.sqlite3")
    done_path = ROOT / "data" / "slovo" / f"extracted{suffix}.json"
    done = json.loads(done_path.read_text(encoding="utf-8")) if done_path.exists() else {}
    jobs = [(word, c) for word, items in candidates.items() if not wanted or word in wanted for c in items[: args.rank]
            if c["id"] not in done and (videos / f"{c['id']}.mp4").exists()]
    jobs = [job for i, job in enumerate(jobs) if i % shards == shard]
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"{len(jobs)} videos to extract", flush=True)
    started = time.time()
    failures = 0
    for index, (word, c) in enumerate(jobs, start=1):
        try:
            clip_id = import_video_motion(
                word, videos / f"{c['id']}.mp4", phrase=word, language="ru-RU", source=SOURCE,
                license_name=LICENSE, signer_id=c["user"], rights_confirmed=True, db_path=db,
            )
            done[c["id"]] = {"word": word, "clip_id": int(clip_id)}
        except Exception as error:  # keep going; report at the end
            failures += 1
            done[c["id"]] = {"word": word, "error": f"{type(error).__name__}: {error}"[:200]}
        if index % 10 == 0 or index == len(jobs):
            done_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
            rate = (time.time() - started) / index
            print(f"{index}/{len(jobs)} done, {failures} failed, {rate:.1f}s per video", flush=True)
    done_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
