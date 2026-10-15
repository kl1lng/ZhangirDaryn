"""Prepare a DosYm video manifest from FluentSigners-50 annotations.

This helper never downloads videos. It joins the official annotation tables by
sample ID and emits only IDs whose matching local video file exists.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


DEFAULT_METADATA_DIR = Path(__file__).resolve().parents[1] / "data/datasets/fluentsigners50"
OFFICIAL_SOURCE = "FluentSigners-50 (KRSL; official project repository)"


def _read_table(path: Path, field: str) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"ID", field}.issubset(reader.fieldnames or ()):
            raise ValueError(f"{path} must contain ID and {field} columns")
        rows: dict[str, str] = {}
        for row in reader:
            sample_id = (row.get("ID") or "").strip()
            value = (row.get(field) or "").strip()
            if not sample_id or not value:
                continue
            if sample_id in rows:
                raise ValueError(f"Duplicate sample ID {sample_id} in {path}")
            rows[sample_id] = value
        return rows


def prepare_manifest(
    video_dir: str | Path,
    output: str | Path,
    *,
    metadata_dir: str | Path = DEFAULT_METADATA_DIR,
    video_pattern: str = "{id}.mp4",
    license_name: str = "Research use only; verify dataset-specific video terms before import",
) -> tuple[int, int]:
    """Write a reviewable manifest for present videos; never downloads or imports."""
    metadata_dir = Path(metadata_dir)
    video_dir = Path(video_dir).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    translations = _read_table(metadata_dir / "russian_translation.csv", "Translation")
    glosses = _read_table(metadata_dir / "gloss_annotation.csv", "Gloss")
    ids = sorted(translations.keys() & glosses.keys(), key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))
    found = missing = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "video_path", "phrase", "source", "license", "rights_confirmed",
            "signer_id", "language", "translations",
        ))
        writer.writeheader()
        for sample_id in ids:
            filename = video_pattern.format(id=sample_id)
            # Prevent a user-supplied pattern from escaping the selected video directory.
            if Path(filename).name != filename or not re.fullmatch(r"[\w.-]+", filename):
                raise ValueError("video_pattern must produce a simple filename")
            video_path = video_dir / filename
            if not video_path.is_file():
                missing += 1
                continue
            found += 1
            writer.writerow({
                "video_path": str(video_path),
                "phrase": glosses[sample_id],
                "source": f"{OFFICIAL_SOURCE}; sample_id={sample_id}",
                "license": license_name,
                # Intentionally false: this requires an explicit human rights review.
                "rights_confirmed": "false",
                "signer_id": "",
                "language": "ru-RU",
                "translations": "",
            })
    return found, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_dir", type=Path, help="Directory containing the officially obtained local videos")
    parser.add_argument("output", type=Path, help="Output CSV manifest (not imported automatically)")
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--video-pattern", default="{id}.mp4", help="Filename template, e.g. '{id}.mp4'")
    args = parser.parse_args()
    found, missing = prepare_manifest(
        args.video_dir, args.output, metadata_dir=args.metadata_dir,
        video_pattern=args.video_pattern,
    )
    print(f"Manifest: {args.output.resolve()} · videos found: {found} · IDs without local video: {missing}")
    print("rights_confirmed=false by design; review dataset terms and the videos before --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
