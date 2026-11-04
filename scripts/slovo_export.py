"""Build a static Russian Sign Language (RSL) preview library from the Slovo extractions.

Reads data/slovo/motion_slovo*.sqlite3 (made by scripts/slovo_extract.py), keeps the best clip per word, and writes
catalog.json + <id>.json in the same shape as backend/export_library.py, plus ATTRIBUTION.md.
Entries are marked sign_language="rsl" and review="pending": they are NOT Kazakh Sign Language and have not been
checked by native signers. Output goes to data/slovo/export/rsl (ignored by git).

  .venv-pwa\Scripts\python.exe scripts/slovo_export.py [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import sqlite3
import statistics as st
import sys
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from backend.import_motion import PUBLIC_METADATA  # noqa: E402

DECIMALS = 4


def round_deep(value):
    if isinstance(value, float):
        return round(value, DECIMALS)
    if isinstance(value, list):
        return [round_deep(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "slovo" / "export" / "rsl"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):  # a previous run may have used different ids
        old.unlink()

    # The database folds case ("С" the letter and "с" the word share a lemma), so group by the original class label.
    candidates = json.loads((ROOT / "data" / "slovo" / "candidates.json").read_text(encoding="utf-8"))
    word_of_video = {c["id"]: word for word, items in candidates.items() for c in items}
    clips: dict[str, list[dict]] = {}
    for db in sorted(glob.glob(str(ROOT / "data" / "slovo" / "motion_slovo*.sqlite3"))):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for clip_id, source_video, frames, fps, blob, meta in con.execute(
            "select id, source_video, frame_count, fps, landmarks_zlib, metadata_json from motion_clips"
        ):
            metadata = json.loads(meta)
            word = word_of_video.get(Path(source_video).stem)
            if word is None:
                continue
            clips.setdefault(word, []).append(
                dict(db=db, id=clip_id, frames=frames, fps=fps, blob=blob, meta=metadata)
            )

    def quality(clip, median_frames):
        m = clip["meta"]
        arms = min(m.get("left_arm_pose_coverage") or 0, m.get("right_arm_pose_coverage") or 0)
        return (m.get("hand_detection_coverage") or 0) + 0.5 * (m.get("body_pose_coverage") or 0) + 0.5 * arms \
            - 0.5 * abs(clip["frames"] - median_frames) / max(median_frames, 1) - (1 if clip["frames"] < 15 else 0)

    catalog, total_bytes = [], 0
    for word, items in sorted(clips.items()):
        median_frames = st.median(c["frames"] for c in items)
        best = max(items, key=lambda c: quality(c, median_frames))
        array = np.load(io.BytesIO(zlib.decompress(best["blob"])), allow_pickle=False).astype(np.float32)
        public = {k: v for k, v in best["meta"].items() if k in PUBLIC_METADATA}
        public.update(fps=best["fps"], shape=list(array.shape), schema_version=1)
        public = {k: round_deep(v) for k, v in public.items()}
        sequence = round_deep(array.astype(float).tolist())
        body = {"label": word, "language": "ru-RU", "sign_language": "rsl", "sequence": sequence, "fps": best["fps"],
                "metadata": public}
        version = hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        motion_id = f"rsl-{version[:12]}"
        motion = {"id": motion_id, **body, "version": version}
        text = json.dumps(motion, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        (out / f"{motion_id}.json").write_text(text, encoding="utf-8")
        total_bytes += len(text.encode())
        catalog.append({"id": motion_id, "label": word, "language": "ru-RU", "sign_language": "rsl", "review": "pending",
                        "metadata": {"fps": best["fps"], "shape": list(array.shape)}, "version": version})
    (out / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "ATTRIBUTION.md").write_text(
        "# Russian Sign Language preview library\n\n"
        "Derived from **Slovo: Russian Sign Language Dataset** (Kapitanov et al., SaluteDevices, 2023), "
        "https://github.com/ai-forever/slovo, under the dataset's public license with attribution and conditions reserved "
        "(a CC BY-SA 4.0 variant). Changes: hand, body-pose and face landmarks were extracted from the original videos with "
        "MediaPipe, one clip per word was selected, coordinates were rounded to 4 decimals. Original videos are not included.\n\n"
        "This is Russian Sign Language, not Kazakh Sign Language, and has not been reviewed by native signers. "
        "Derived data are shared under the same license terms.\n",
        encoding="utf-8",
    )
    print(f"{len(catalog)} words, {total_bytes / 1e6:.1f} MB of JSON in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
