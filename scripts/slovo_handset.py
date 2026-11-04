"""Turn the Slovo hand-landmark JSON (all 20 000 videos) into one compact array for camera-matching experiments.

  python scripts/slovo_handset.py            # writes data/slovo/handset.npz

Each video becomes STEPS time steps x 2 hand slots x 21 landmarks x 3. Hands are put in slots by the x position of the wrist
(left in the image first); a single hand always goes to slot 0, so no handedness label is needed. Values stay in image
coordinates; zero means "no hand".
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
STEPS = 24
KEY = re.compile(rb'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})": \[')


def videos():
    buffer, key = b"", None
    with gzip.open(ROOT / "data" / "slovo" / "slovo_mediapipe.json.gz", "rb") as stream:
        while True:
            chunk = stream.read(16 << 20)
            if not chunk:
                break
            buffer += chunk
            while True:
                match = KEY.search(buffer, 1 if key else 0)
                if not match:
                    break
                if key:
                    yield key, buffer[: match.start()]
                key = match.group(1).decode()
                buffer = buffer[match.start():]
    if key:
        yield key, buffer


def to_frames(key: str, raw: bytes) -> np.ndarray:
    raw = raw.rstrip().rstrip(b",").rstrip(b"}")
    frames = json.loads(b"{" + raw + b"}")[key]
    out = np.zeros((len(frames), 2, 21, 3), np.float32)
    for i, frame in enumerate(frames):
        hands = [np.array([[p["x"], p["y"], p["z"]] for p in frame[name]], np.float32)
                 for name in ("hand 1", "hand 2", "hand 3") if frame.get(name) and len(frame[name]) == 21]
        hands = sorted(hands, key=lambda h: h[0, 0])[:2]
        for slot, hand in enumerate(hands):
            out[i, slot] = hand
    return out


def resample(frames: np.ndarray) -> np.ndarray:
    positions = np.linspace(0, len(frames) - 1, STEPS)
    lower = np.floor(positions).astype(int)
    upper = np.minimum(lower + 1, len(frames) - 1)
    weight = (positions - lower)[:, None, None, None]
    both = (frames[lower] != 0).any(axis=(2, 3), keepdims=True) & (frames[upper] != 0).any(axis=(2, 3), keepdims=True)
    mixed = frames[lower] * (1 - weight) + frames[upper] * weight
    nearest = np.where(weight < 0.5, frames[lower], frames[upper])
    return np.where(both, mixed, nearest)


def main() -> None:
    rows = {r["attachment_id"]: r for r in csv.DictReader(open(ROOT / "data/slovo/annotations.csv", encoding="utf-8"), delimiter="\t")}
    ids, labels, users, train, data = [], [], [], [], []
    for index, (key, raw) in enumerate(videos()):
        row = rows.get(key)
        if row is None or row["text"] == "no_event":
            continue
        frames = to_frames(key, raw)
        if len(frames) < 4:
            continue
        data.append(resample(frames).astype(np.float16))
        ids.append(key); labels.append(row["text"]); users.append(row["user_id"]); train.append(row["train"] == "True")
        if len(ids) % 2000 == 0:
            print(len(ids), "videos", flush=True)
    out = ROOT / "data" / "slovo" / "handset.npz"
    np.savez_compressed(out, ids=np.array(ids), labels=np.array(labels), users=np.array(users), train=np.array(train),
                        data=np.stack(data))
    print("saved", out, np.stack(data).shape, f"{out.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
