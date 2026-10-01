"""Подготовка последовательностей для supervised-модели из проектов и SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import config
from src.motion_db import clip_tracking_eligible, load_motion_library
from src.normalize import normalize_sequence, pad_or_truncate


def _project_path(path: str | Path) -> str:
    """Resolve stored relative paths from the project root, not process CWD."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(config.BASE_DIR) / candidate
    return str(candidate.resolve()).casefold()


def _hand_detection_coverage(sequence: np.ndarray) -> float:
    """Fraction of frames with a usable hand skeleton in raw landmarks."""
    hands = np.asarray(sequence, dtype=np.float32)[:, :config.HAND_FEATURES]
    if hands.shape[1] != config.HAND_FEATURES or not len(hands):
        return 0.0
    points = hands.reshape(-1, config.NUM_HANDS, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK)
    wrist = points[:, :, :1, :2]
    extent = np.linalg.norm(points[:, :, 1:, :2] - wrist, axis=-1).max(axis=2)
    return float(np.any(extent > 0.012, axis=1).mean())


def _as_sequences(value: Any) -> list[np.ndarray]:
    """Понимает сырой проектный файл: один клип или набор клипов."""
    if isinstance(value, np.ndarray):
        array = value
    else:
        try:
            array = np.asarray(value, dtype=object)
        except (TypeError, ValueError):
            return []
    candidates: list[Any]
    if array.ndim == 3:
        candidates = [array[index] for index in range(array.shape[0])]
    elif array.ndim == 2:
        candidates = [array]
    elif array.ndim == 1 and array.dtype == object:
        candidates = list(array)
    else:
        return []

    sequences = []
    for candidate in candidates:
        try:
            seq = np.asarray(candidate, dtype=np.float32)
        except (TypeError, ValueError):
            continue
        if (seq.ndim == 2 and len(seq) and seq.shape[1] in
                (config.HAND_FEATURES, config.TOTAL_FEATURES) and np.isfinite(seq).all()):
            if seq.shape[1] == config.HAND_FEATURES:
                seq = np.pad(seq, ((0, 0), (0, config.FACE_FEATURES)))
            sequences.append(seq)
    return sequences


def collect_training_sequences(
    projects: dict[str, dict[str, Any]],
    *,
    include_motion_library: bool = True,
    include_groups: bool = False,
) -> tuple[dict[str, list[np.ndarray]], dict[str, int]] | tuple[dict[str, list[np.ndarray]], dict[str, int], dict[str, list[str]]]:
    """Собирает размеченные видео-последовательности по текстовым классам.

    Если motion-клип ссылается на исходное видео, которое уже покрыто
    landmarks_raw.npy того же проекта/класса, второй раз его не добавляем.
    """
    sequences_by_label: dict[str, list[np.ndarray]] = {}
    groups_by_label: dict[str, list[str]] = {}
    covered_project_recordings: set[tuple[str, str, int, int]] = set()
    covered_landmark_paths: set[str] = set()

    for project in projects.values():
        project_path = Path(project["path"])
        landmarks_path = Path(project.get("landmarks_path", project_path / "landmarks.npy"))
        if not project.get("has_landmarks"):
            continue
        label = str(project.get("name_kz", "")).strip()
        if not label:
            continue
        try:
            metadata_path = project_path / "landmarks_meta.json"
            with metadata_path.open("r", encoding="utf-8") as stream:
                metadata = json.load(stream)
            if metadata.get("format") != "raw_frame_landmarks":
                continue  # Legacy normalized arrays have already lost absolute hand placement.
            landmarks_path = project_path / metadata.get("data_file", "landmarks_raw.npy")
            if not landmarks_path.is_file():
                continue
            loaded = np.load(landmarks_path, allow_pickle=True)
            sequences = _as_sequences(loaded)
        except (OSError, ValueError, EOFError, json.JSONDecodeError):
            continue
        if sequences:
            source_videos = metadata.get("source_videos", [])
            signer_ids = metadata.get("signer_ids", {})
            for index, sequence in enumerate(sequences):
                if _hand_detection_coverage(sequence) < config.MOTION_MIN_HAND_COVERAGE:
                    continue
                source = source_videos[index] if index < len(source_videos) else None
                signer = signer_ids.get(Path(source).name) if source else None
                if signer:
                    group = f"signer:{signer}"
                elif source:
                    group = f"video:{_project_path(project_path / source)}"
                else:
                    group = f"project:{project_path.resolve()}:{index}"
                sequences_by_label.setdefault(label, []).append(sequence)
                groups_by_label.setdefault(label, []).append(group)
                if source:
                    video_path = Path(source)
                    if not video_path.is_absolute():
                        video_path = project_path / video_path
                    covered_project_recordings.add((
                        label.casefold(), _project_path(video_path), 0, len(sequence)
                    ))
            if source_videos:
                covered_landmark_paths.add(_project_path(landmarks_path))

    if include_motion_library:
        covered_motion_recordings: set[tuple[str, str, int, int]] = set()
        for clip in load_motion_library():
            label = str(clip.get("lemma", "")).strip()
            source_video = clip.get("source_video")
            if not label:
                continue
            if not clip_tracking_eligible(clip.get("metadata")):
                continue
            sequence = np.asarray(clip["sequence"], dtype=np.float32)
            start_frame = int(clip.get("start_frame", 0))
            end_frame = clip.get("end_frame")
            end_frame = int(end_frame) if end_frame is not None else start_frame + len(sequence)
            source_aliases = []
            if source_video:
                try:
                    source_aliases.append(_project_path(source_video))
                except OSError:
                    pass
            source_hash = (clip.get("metadata") or {}).get("source_video_sha256")
            if source_hash:
                source_aliases.append(f"sha256:{source_hash}")
            recording_keys = [
                (label.casefold(), source, start_frame, end_frame)
                for source in source_aliases
            ]
            if any(key in covered_project_recordings or key in covered_motion_recordings
                   for key in recording_keys):
                continue
            covered_motion_recordings.update(recording_keys)
            landmarks_source = clip.get("metadata", {}).get("landmarks_path")
            if landmarks_source:
                try:
                    if _project_path(landmarks_source) in covered_landmark_paths:
                        continue
                except OSError:
                    pass
            if (sequence.ndim == 2 and len(sequence) and sequence.shape[1] in
                    (config.HAND_FEATURES, config.TOTAL_FEATURES) and np.isfinite(sequence).all()):
                if sequence.shape[1] == config.HAND_FEATURES:
                    sequence = np.pad(sequence, ((0, 0), (0, config.FACE_FEATURES)))
                sequences_by_label.setdefault(label, []).append(sequence)
                signer = clip.get("signer_id")
                if signer:
                    group = f"signer:{signer}"
                elif source_video:
                    group_source = f"sha256:{source_hash}" if source_hash else _project_path(source_video)
                    group = f"video:{group_source}"
                else:
                    group = f"clip:{clip.get('clip_id', len(groups_by_label.get(label, [])))}"
                groups_by_label.setdefault(label, []).append(group)

    counts = {label: len(sequences) for label, sequences in sorted(sequences_by_label.items())}
    if include_groups:
        return sequences_by_label, counts, groups_by_label
    return sequences_by_label, counts


def prepare_training_data(
    sequences_by_label: dict[str, list[np.ndarray]],
    *,
    groups_by_label: dict[str, list[str]] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]] | tuple[np.ndarray, np.ndarray, dict[str, int], np.ndarray]:
    """Нормализует/паддит каждый clip и возвращает X, y и стабильную label map."""
    labels = sorted(label for label, sequences in sequences_by_label.items() if sequences)
    label_map = {label: index for index, label in enumerate(labels)}
    samples: list[np.ndarray] = []
    targets: list[int] = []
    groups: list[str] = []
    for label in labels:
        for sequence_index, sequence in enumerate(sequences_by_label[label]):
            array = np.asarray(sequence, dtype=np.float32)
            if array.ndim != 2 or array.shape[1] != config.TOTAL_FEATURES or not len(array):
                continue
            normalized = normalize_sequence(array)
            samples.append(pad_or_truncate(normalized, config.SEQUENCE_LENGTH).astype(np.float32))
            targets.append(label_map[label])
            if groups_by_label is not None:
                label_groups = groups_by_label.get(label, [])
                groups.append(label_groups[sequence_index] if sequence_index < len(label_groups)
                              else f"sample:{label}:{sequence_index}")
    if not samples:
        empty = (
            np.zeros((0, config.SEQUENCE_LENGTH, config.TOTAL_FEATURES), dtype=np.float32),
            np.zeros((0,), dtype=np.int64),
            label_map,
        )
        if groups_by_label is not None:
            return (*empty, np.asarray([], dtype=str))
        return empty
    result = (np.stack(samples), np.asarray(targets, dtype=np.int64), label_map)
    if groups_by_label is not None:
        return (*result, np.asarray(groups, dtype=str))
    return result
