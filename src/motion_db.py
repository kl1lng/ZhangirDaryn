"""SQLite-хранилище реальных жестовых motion-клипов.

Клип хранится как сжатый NumPy-массив кадров. Это позволяет:
1) не терять исходную временную динамику видео;
2) привязать движение к слову/фразе и источнику;
3) позже отдавать один и тот же клип WebGL-аватару или API.
"""

from __future__ import annotations

import io
import hashlib
import json
import math
import re
import sqlite3
import zlib
from pathlib import Path
from typing import Any

import numpy as np

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS gestures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma TEXT NOT NULL,
    phrase TEXT,
    language TEXT NOT NULL DEFAULT 'kk-KZ',
    gloss TEXT,
    source TEXT,
    license TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(lemma, phrase, language)
);

CREATE TABLE IF NOT EXISTS motion_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gesture_id INTEGER NOT NULL REFERENCES gestures(id) ON DELETE CASCADE,
    source_video TEXT,
    signer_id TEXT,
    fps REAL NOT NULL DEFAULT 30,
    frame_count INTEGER NOT NULL,
    feature_count INTEGER NOT NULL,
    start_frame INTEGER NOT NULL DEFAULT 0,
    end_frame INTEGER,
    landmarks_zlib BLOB NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gestures_lemma ON gestures(lemma);
CREATE INDEX IF NOT EXISTS idx_clips_gesture ON motion_clips(gesture_id);

CREATE TABLE IF NOT EXISTS gesture_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gesture_id INTEGER NOT NULL REFERENCES gestures(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    alias TEXT NOT NULL,
    normalized TEXT NOT NULL,
    UNIQUE(language, normalized)
);
CREATE INDEX IF NOT EXISTS idx_gesture_aliases_gesture ON gesture_aliases(gesture_id);
"""


class _ClosingConnection(sqlite3.Connection):
    """SQLite context manager that also releases the file handle on Windows."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.MOTION_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=_ClosingConnection)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


def _pack_motion(sequence: np.ndarray) -> bytes:
    array = np.asarray(sequence, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != config.TOTAL_FEATURES:
        raise ValueError(
            f"Motion должен иметь форму (кадры, {config.TOTAL_FEATURES}), "
            f"получено {array.shape}"
        )
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return zlib.compress(buffer.getvalue(), level=6)


def _unpack_motion(blob: bytes) -> np.ndarray:
    raw = zlib.decompress(blob)
    return np.load(io.BytesIO(raw), allow_pickle=False)


def register_gesture(
    lemma: str,
    phrase: str | None = None,
    *,
    language: str = "kk-KZ",
    gloss: str | None = None,
    source: str | None = None,
    license_name: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    with connect(db_path) as db:
        # Старый импорт мог создать lemma с phrase=NULL, а синхронизация видео
        # затем добавила такую же lemma с phrase. Сливаем эти технические дубли,
        # сохраняя все motion-клипы на основной записи.
        if phrase is not None:
            exact = db.execute(
                "SELECT id FROM gestures WHERE lemma=? AND phrase=? AND language=?",
                (lemma.strip().lower(), phrase, language),
            ).fetchone()
            legacy = db.execute(
                "SELECT id FROM gestures WHERE lemma=? AND phrase IS NULL AND language=?",
                (lemma.strip().lower(), language),
            ).fetchone()
            if exact and legacy and int(exact[0]) != int(legacy[0]):
                db.execute(
                    "UPDATE motion_clips SET gesture_id=? WHERE gesture_id=?",
                    (int(exact[0]), int(legacy[0])),
                )
                db.execute("DELETE FROM gestures WHERE id=?", (int(legacy[0]),))
        elif phrase is None:
            existing_phrase = db.execute(
                "SELECT id, phrase FROM gestures WHERE lemma=? AND language=? ORDER BY id LIMIT 1",
                (lemma.strip().lower(), language),
            ).fetchone()
            if existing_phrase and existing_phrase[1] is not None:
                return int(existing_phrase[0])
        if phrase is not None:
            normalized_phrase = tuple(normalize_text(phrase))
            normalized_lemma = tuple(normalize_text(lemma))
            if normalized_phrase:
                # Punctuation/case are presentation, not lexical identity. A
                # batch may contain e.g. "Сәлем, досым!" and "сәлем досым";
                # registering those as separate phrases makes exact lookup
                # ambiguous after enough imports. Preserve the first display
                # form but attach additional recordings to its same gesture.
                candidates = db.execute(
                    "SELECT id, lemma, phrase FROM gestures WHERE language=? AND phrase IS NOT NULL",
                    (language,),
                ).fetchall()
                canonical_match = next(
                    (candidate for candidate in candidates
                     if tuple(normalize_text(candidate[2] or "")) == normalized_phrase),
                    None,
                )
                if canonical_match is not None:
                    gesture_id = int(canonical_match[0])
                    if tuple(normalize_text(canonical_match[1])) != normalized_lemma:
                        raise ValueError(
                            f"Фраза «{phrase}» уже зарегистрирована с другой леммой "
                            f"«{canonical_match[1]}»; проверьте gloss/разметку"
                        )
                    db.execute(
                        """UPDATE gestures SET gloss=COALESCE(?, gloss),
                                  source=COALESCE(?, source), license=COALESCE(?, license)
                           WHERE id=?""",
                        (gloss, source, license_name, gesture_id),
                    )
                    return gesture_id
        current = db.execute(
            "SELECT id FROM gestures WHERE lemma=? AND phrase IS ? AND language=?",
            (lemma.strip().lower(), phrase, language),
        ).fetchone()
        current_id = int(current[0]) if current else None
        for label in (lemma, phrase):
            normalized = " ".join(normalize_text(label or ""))
            if not normalized:
                continue
            alias_owner = db.execute(
                "SELECT gesture_id, alias FROM gesture_aliases WHERE language=? AND normalized=?",
                (language, normalized),
            ).fetchone()
            if alias_owner and int(alias_owner[0]) != current_id:
                raise ValueError(
                    f"Название «{label}» уже используется как вариант «{alias_owner[1]}» другого жеста"
                )
        db.execute(
            """INSERT INTO gestures(lemma, phrase, language, gloss, source, license)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(lemma, phrase, language) DO UPDATE SET
                 gloss=COALESCE(excluded.gloss, gestures.gloss),
                 source=COALESCE(excluded.source, gestures.source),
                 license=COALESCE(excluded.license, gestures.license)""",
            (lemma.strip().lower(), phrase, language, gloss, source, license_name),
        )
        row = db.execute(
            "SELECT id FROM gestures WHERE lemma=? AND phrase IS ? AND language=?",
            (lemma.strip().lower(), phrase, language),
        ).fetchone()
        if row is None:
            raise RuntimeError("Не удалось зарегистрировать жест")
        return int(row[0])


def register_gesture_alias(
    gesture_id: int,
    alias: str,
    *,
    language: str = "kk-KZ",
    db_path: str | Path | None = None,
) -> None:
    """Привязывает явно заданную словоформу/синоним без автоперевода смысла."""
    register_gesture_aliases(gesture_id, [alias], language=language, db_path=db_path)


def register_gesture_aliases(
    gesture_id: int,
    aliases: list[str],
    *,
    language: str = "kk-KZ",
    db_path: str | Path | None = None,
) -> None:
    """Пакетно записывает варианты, отклоняя конфликт до любых изменений."""
    normalized_aliases: dict[str, str] = {}
    for alias in aliases:
        display_alias = " ".join(str(alias).split())
        normalized = " ".join(normalize_text(display_alias))
        if not normalized:
            raise ValueError("Вариант названия жеста пуст или не содержит букв/цифр")
        normalized_aliases.setdefault(normalized, display_alias)
    if not normalized_aliases:
        return
    with connect(db_path) as db:
        gesture = db.execute(
            "SELECT language FROM gestures WHERE id=?", (int(gesture_id),)
        ).fetchone()
        if gesture is None:
            raise ValueError("Жест не найден")
        label_rows = db.execute(
            "SELECT id, lemma, phrase FROM gestures WHERE language=?", (language,)
        ).fetchall()
        normalized_labels: dict[str, int] = {}
        for label_id, lemma, phrase in label_rows:
            for label in (lemma, phrase):
                normalized = " ".join(normalize_text(label or ""))
                if normalized:
                    normalized_labels.setdefault(normalized, int(label_id))
        for normalized, display_alias in normalized_aliases.items():
            existing = db.execute(
                "SELECT gesture_id FROM gesture_aliases WHERE language=? AND normalized=?",
                (language, normalized),
            ).fetchone()
            if existing and int(existing[0]) != int(gesture_id):
                raise ValueError(f"Вариант «{display_alias}» уже привязан к другому жесту")
            label_owner = normalized_labels.get(normalized)
            if label_owner is not None and label_owner != int(gesture_id):
                raise ValueError(f"Вариант «{display_alias}» совпадает с названием другого жеста")
        db.executemany(
            """INSERT INTO gesture_aliases(gesture_id, language, alias, normalized)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(language, normalized) DO UPDATE SET alias=excluded.alias""",
            [
                (int(gesture_id), language, display_alias, normalized)
                for normalized, display_alias in normalized_aliases.items()
            ],
        )


def add_motion_clip(
    gesture_id: int,
    sequence: np.ndarray,
    *,
    source_video: str | None = None,
    signer_id: str | None = None,
    fps: float = 30.0,
    start_frame: int = 0,
    end_frame: int | None = None,
    body_pose: np.ndarray | None = None,
    body_pose_world: np.ndarray | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> int:
    array = np.asarray(sequence, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] == 0:
        raise ValueError("Motion-клип должен содержать хотя бы один кадр")
    if not np.isfinite(array).all():
        raise ValueError("Motion-клип содержит NaN или бесконечные координаты")
    if not math.isfinite(float(fps)) or float(fps) <= 0:
        raise ValueError(f"Некорректная частота кадров: {fps}")
    blob = _pack_motion(array)
    clip_metadata = dict(metadata or {})
    if body_pose is not None:
        pose = np.asarray(body_pose, dtype=np.float32)
        if pose.ndim != 2 or pose.shape[0] != array.shape[0] or pose.shape[1] != 18:
            raise ValueError("body_pose должен иметь форму (кадры, 18): плечи, локти и запястья")
        if not np.isfinite(pose).all():
            raise ValueError("body_pose содержит NaN или бесконечные координаты")
        # В pose-канале используются normalized image coordinates: по 3 координаты
        # для левого/правого плеча, локтя и запястья на каждом кадре.
        clip_metadata["body_pose_landmarks"] = pose.tolist()
        joints = np.any(np.abs(pose.reshape(len(pose), 6, 3)) > 1e-8, axis=2)
        left_arm = np.all(joints[:, (0, 2, 4)], axis=1)
        right_arm = np.all(joints[:, (1, 3, 5)], axis=1)
        clip_metadata.update({
            "body_pose_frames": int(np.any(joints, axis=1).sum()),
            "body_pose_coverage": float(np.all(joints, axis=1).mean()),
            "left_arm_pose_coverage": float(left_arm.mean()),
            "right_arm_pose_coverage": float(right_arm.mean()),
        })
    if body_pose_world is not None:
        world = np.asarray(body_pose_world, dtype=np.float32)
        if world.shape != (array.shape[0], 18) or not np.isfinite(world).all():
            raise ValueError("body_pose_world должен иметь форму (кадры, 18) и конечные координаты")
        clip_metadata["body_pose_world_landmarks"] = world.tolist()
    with connect(db_path) as db:
        if source_video:
            existing = db.execute(
                """SELECT id FROM motion_clips
                   WHERE gesture_id=? AND source_video=? AND signer_id IS ?
                     AND start_frame=? AND end_frame IS ?
                   ORDER BY id LIMIT 1""",
                (gesture_id, source_video, signer_id, int(start_frame), end_frame),
            ).fetchone()
            if existing:
                db.execute(
                    """UPDATE motion_clips SET fps=?, frame_count=?, feature_count=?,
                       landmarks_zlib=?, metadata_json=? WHERE id=?""",
                    (float(fps), int(array.shape[0]), int(array.shape[1]), blob,
                     json.dumps(clip_metadata, ensure_ascii=False), int(existing[0])),
                )
                return int(existing[0])
        cursor = db.execute(
            """INSERT INTO motion_clips(
                gesture_id, source_video, signer_id, fps, frame_count,
                feature_count, start_frame, end_frame, landmarks_zlib, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gesture_id, source_video, signer_id, float(fps), int(array.shape[0]),
                int(array.shape[1]), int(start_frame), end_frame, blob,
                json.dumps(clip_metadata, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def import_landmarks_file(
    lemma: str,
    landmarks_path: str | Path,
    *,
    source_video: str | None = None,
    phrase: str | None = None,
    source: str = "local",
    license_name: str | None = None,
    fps: float = 30.0,
    signer_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[int]:
    """Импортирует один .npy с одной или несколькими motion-последовательностями."""
    raw = np.load(landmarks_path, allow_pickle=True)
    sequences: list[np.ndarray] = []
    if raw.ndim == 3:
        sequences = [np.asarray(item, dtype=np.float32) for item in raw]
    elif raw.ndim == 2:
        sequences = [np.asarray(raw, dtype=np.float32)]
    else:
        raise ValueError(f"Неподдерживаемая форма landmarks: {raw.shape}")

    gesture_id = register_gesture(
        lemma, phrase, source=source, license_name=license_name, db_path=db_path
    )
    clip_ids = []
    for index, sequence in enumerate(sequences):
        clip_ids.append(add_motion_clip(
            gesture_id, sequence, source_video=source_video,
            signer_id=signer_id, fps=fps,
            metadata={"import_index": index, "landmarks_path": str(landmarks_path)},
            db_path=db_path,
        ))
    return clip_ids


def import_video_motion(
    lemma: str,
    video_path: str | Path,
    *,
    phrase: str | None = None,
    language: str = "kk-KZ",
    source: str = "local-video",
    license_name: str | None = None,
    signer_id: str | None = None,
    input_mirrored: bool = False,
    rights_confirmed: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    extraction_cache: dict[str, dict[tuple[Any, ...], tuple[np.ndarray, np.ndarray | None, str]]] | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Извлекает необработанные кадры из видео и сохраняет их для playback.

    Здесь намеренно не вызывается normalize_sequence: нормализация убирает
    положение запястья, а motion playback должен сохранить его траекторию.
    """
    import cv2
    from src.extract_landmarks import (
        FACE_EXTRACTOR_VERSION, HAND_EXTRACTOR_VERSION, extract_from_video,
    )

    path = Path(video_path).resolve()
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Не удалось открыть видео: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    frame_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    capture.release()
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    if start_seconds is not None and (
        not math.isfinite(float(start_seconds)) or float(start_seconds) < 0
    ):
        raise ValueError("start_seconds должен быть конечным неотрицательным числом")
    if end_seconds is not None and (not math.isfinite(float(end_seconds)) or float(end_seconds) <= 0):
        raise ValueError("end_seconds должен быть конечным положительным числом")
    start_frame = int(round(float(start_seconds or 0.0) * fps))
    explicit_interval = start_seconds is not None or end_seconds is not None
    end_frame = total_frames if end_seconds is None else int(round(float(end_seconds) * fps))
    if start_frame < 0 or end_frame <= start_frame or end_frame > total_frames:
        raise ValueError(
            f"Интервал [{start_seconds or 0:g}, {end_seconds if end_seconds is not None else total_frames / fps:g}) с "
            f"FPS {fps:g} выходит за пределы видео ({total_frames} кадров)"
        )
    stat = path.stat()
    source_video = str(path)
    digest = hashlib.sha256()
    with path.open("rb") as video_file:
        for chunk in iter(lambda: video_file.read(1024 * 1024), b""):
            digest.update(chunk)
    video_sha256 = digest.hexdigest()
    source_metadata = {
        "coordinate_space": "mediapipe_normalized_image",
        "frame_width": frame_width if frame_width > 0 else None,
        "frame_height": frame_height if frame_height > 0 else None,
        "image_aspect_ratio": (
            frame_width / frame_height if frame_width > 0 and frame_height > 0 else None
        ),
        "raw_video": True,
        "source_fps": fps,
        "source_size_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_video_sha256": video_sha256,
        "face_extractor_version": FACE_EXTRACTOR_VERSION,
        "hand_extractor_version": HAND_EXTRACTOR_VERSION,
        "input_mirrored": bool(input_mirrored),
        "rights_confirmed": bool(rights_confirmed),
        "clip_start_seconds": start_frame / fps,
        "clip_end_seconds": end_frame / fps,
    }
    from src.extract_landmarks import POSE_MODEL_PATH, POSE_EXTRACTOR_VERSION
    pose_model_stat = Path(POSE_MODEL_PATH).stat() if Path(POSE_MODEL_PATH).is_file() else None
    source_metadata.update({
        "pose_extractor_version": POSE_EXTRACTOR_VERSION,
        "pose_model_available": pose_model_stat is not None,
        "pose_model_mtime_ns": pose_model_stat.st_mtime_ns if pose_model_stat else None,
    })

    # Не гоняем MediaPipe повторно, если исходное видео не менялось.
    with connect(db_path) as db:
        cached = db.execute(
            """SELECT c.id, c.metadata_json, g.source, g.license FROM gestures g
               JOIN motion_clips c ON c.gesture_id=g.id
               WHERE g.lemma=? AND g.phrase IS ? AND g.language=?
                 AND c.source_video=? AND c.signer_id IS ?
                 AND c.start_frame=? AND c.end_frame=?
               ORDER BY c.id DESC LIMIT 1""",
            (lemma.strip().lower(), phrase, language, source_video, signer_id,
             start_frame, end_frame),
        ).fetchone()
    if cached:
        try:
            previous_metadata = json.loads(cached[1])
        except (TypeError, json.JSONDecodeError):
            previous_metadata = {}
        if (all(previous_metadata.get(key) == value for key, value in source_metadata.items())
                and cached[2] == source and cached[3] == license_name):
            return int(cached[0])

    # A copied/imported video is still the same training example. Avoid counting
    # another filesystem copy as independent signer data or re-running MediaPipe.
    with connect(db_path) as db:
        candidates = db.execute(
            """SELECT c.id, c.metadata_json, g.source, g.license FROM gestures g
               JOIN motion_clips c ON c.gesture_id=g.id
               WHERE g.lemma=? AND g.phrase IS ? AND g.language=?
                 AND c.signer_id IS ? AND c.start_frame=? AND c.end_frame=?
                 AND c.metadata_json LIKE ? ORDER BY c.id DESC""",
            (lemma.strip().lower(), phrase, language, signer_id, start_frame, end_frame,
             f"%{video_sha256}%"),
        ).fetchall()
    for candidate in candidates:
        try:
            duplicate_metadata = json.loads(candidate[1])
        except (TypeError, json.JSONDecodeError):
            continue
        compatibility_keys = (
            "input_mirrored", "pose_extractor_version",
            "pose_model_available", "pose_model_mtime_ns",
        )
        if (duplicate_metadata.get("source_video_sha256") == video_sha256
                and all(duplicate_metadata.get(key) == source_metadata.get(key)
                        for key in compatibility_keys)
                and candidate[2] == source and candidate[3] == license_name):
            return int(candidate[0])

    cache_key = (
        video_sha256, bool(input_mirrored), FACE_EXTRACTOR_VERSION,
        HAND_EXTRACTOR_VERSION, POSE_EXTRACTOR_VERSION,
        source_metadata["pose_model_mtime_ns"],
    )
    cached_extraction = extraction_cache.get(str(path), {}).get(cache_key) if extraction_cache is not None else None
    if cached_extraction is None:
        raw_frames = extract_from_video(
            str(path), input_mirrored=input_mirrored,
            start_frame=start_frame if extraction_cache is None else 0,
            end_frame=end_frame if extraction_cache is None else total_frames,
        )
        if not raw_frames:
            raise ValueError(f"В видео не удалось извлечь landmarks: {path.name}")
        full_sequence = np.asarray(raw_frames, dtype=np.float32)
        if extraction_cache is not None and len(full_sequence) != total_frames:
            raise ValueError(
                f"Для полного видео ожидалось {total_frames} кадров, "
                f"MediaPipe извлёк {len(full_sequence)}"
            )
        body_pose_full = None
        body_pose_world_full = None
        pose_status = "model_missing_or_pose_not_detected"
        try:
            from src.extract_landmarks import extract_body_pose_from_video
            extracted_pose = extract_body_pose_from_video(
                str(path), expected_frames=len(full_sequence),
                start_frame=0 if extraction_cache is not None else start_frame,
                end_frame=total_frames if extraction_cache is not None else end_frame,
                include_world=True,
            )
            if isinstance(extracted_pose, tuple):
                body_pose_full, body_pose_world_full = extracted_pose
            else:
                body_pose_full = extracted_pose
        except (ImportError, RuntimeError, ValueError, OSError) as error:
            pose_status = f"unavailable: {error}"
        else:
            pose_status = "available" if body_pose_full is not None else pose_status
        if extraction_cache is not None:
            extraction_cache.setdefault(str(path), {})[cache_key] = (
                full_sequence, body_pose_full, body_pose_world_full, pose_status
            )
            raw_frames = full_sequence[start_frame:end_frame]
            body_pose = body_pose_full[start_frame:end_frame] if body_pose_full is not None else None
            body_pose_world = body_pose_world_full[start_frame:end_frame] if body_pose_world_full is not None else None
        else:
            raw_frames = full_sequence
            body_pose = body_pose_full
            body_pose_world = body_pose_world_full
    else:
        full_sequence, body_pose_full, body_pose_world_full, pose_status = cached_extraction
        raw_frames = full_sequence[start_frame:end_frame]
        body_pose = body_pose_full[start_frame:end_frame] if body_pose_full is not None else None
        body_pose_world = body_pose_world_full[start_frame:end_frame] if body_pose_world_full is not None else None
    if len(raw_frames) == 0:
        raise ValueError(f"В видео не удалось извлечь landmarks: {path.name}")
    sequence = np.asarray(raw_frames, dtype=np.float32)
    if explicit_interval and len(sequence) != end_frame - start_frame:
        raise ValueError(
            f"Для интервала [{start_frame}, {end_frame}) ожидалось "
            f"{end_frame - start_frame} кадров, MediaPipe извлёк {len(sequence)}"
        )
    hand_points = sequence[:, :config.HAND_FEATURES].reshape(-1, config.NUM_HANDS, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK)
    wrist = hand_points[:, :, :1, :2]
    hand_extent = np.linalg.norm(hand_points[:, :, 1:, :2] - wrist, axis=-1).max(axis=2)
    visible_hands = hand_extent > 0.012
    visible_frames = np.any(visible_hands, axis=1)
    detected_count = int(visible_frames.sum())
    coverage = detected_count / max(len(sequence), 1)
    face_points = sequence[:, config.HAND_FEATURES:config.TOTAL_FEATURES]
    visible_face_frames = np.any(np.abs(face_points) > 1e-6, axis=1)
    face_detected_count = int(visible_face_frames.sum())
    face_coverage = face_detected_count / max(len(sequence), 1)
    if detected_count == 0 or coverage < 0.10:
        raise ValueError(
            f"В {path.name} найдено слишком мало кадров с руками "
            f"({detected_count}/{len(sequence)}, {coverage:.0%}); клип не сохранён"
        )
    gesture_id = register_gesture(
        lemma, phrase, language=language, source=source,
        license_name=license_name, db_path=db_path,
    )
    source_metadata.update({
        "frame_count": int(len(sequence)),
        "frames_with_hands": detected_count,
        "hand_detection_coverage": coverage,
        "frames_with_face": face_detected_count,
        "face_detection_coverage": face_coverage,
        "training_eligible": coverage >= config.MOTION_MIN_HAND_COVERAGE,
        "training_exclusion_reason": (
            None if coverage >= config.MOTION_MIN_HAND_COVERAGE
            else f"hand_detection_coverage_below_{config.MOTION_MIN_HAND_COVERAGE:.0%}"
        ),
        "hands_detected_left": int(visible_hands[:, 0].sum()),
        "hands_detected_right": int(visible_hands[:, 1].sum()),
        "extractor": "mediapipe-hand-landmarker",
    })
    if body_pose is not None and len(body_pose) != len(sequence):
        body_pose = None
        body_pose_world = None
        pose_status = "unavailable: pose/frame count mismatch"
    if body_pose_world is not None and len(body_pose_world) != len(sequence):
        body_pose_world = None
    source_metadata["body_pose_status"] = pose_status
    return add_motion_clip(
        gesture_id, sequence, source_video=source_video, signer_id=signer_id,
        fps=fps, start_frame=start_frame, end_frame=end_frame,
        body_pose=body_pose, body_pose_world=body_pose_world, metadata=source_metadata,
        db_path=db_path,
    )


def backfill_video_geometry_metadata(db_path: str | Path | None = None) -> int:
    """Recover missing source-frame dimensions without touching stored motion."""
    import cv2

    updated = 0
    with connect(db_path) as db:
        label_rows = db.execute(
            "SELECT language, lemma FROM gestures ORDER BY language, lemma"
        ).fetchall()
        rows = db.execute(
            "SELECT id, source_video, metadata_json FROM motion_clips "
            "WHERE source_video IS NOT NULL"
        ).fetchall()
        for clip_id, source_video, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if metadata.get("image_aspect_ratio"):
                continue
            path = Path(source_video).expanduser()
            if not path.is_absolute():
                path = Path(config.BASE_DIR) / path
            if not path.is_file():
                continue
            capture = cv2.VideoCapture(str(path))
            try:
                if not capture.isOpened():
                    continue
                width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
                height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            finally:
                capture.release()
            if width <= 0 or height <= 0:
                continue
            metadata.update({
                "frame_width": width,
                "frame_height": height,
                "image_aspect_ratio": width / height,
            })
            db.execute(
                "UPDATE motion_clips SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), clip_id),
            )
            updated += 1
    return updated


def clip_tracking_eligible(metadata: str | dict[str, Any] | None) -> bool:
    """Reject known low-coverage clips from translation playback; keep legacy unknowns."""
    try:
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        metadata = metadata or {}
        if metadata.get("training_eligible") is False:
            return False
        coverage = metadata.get("hand_detection_coverage")
        return coverage is None or float(coverage) >= config.MOTION_MIN_HAND_COVERAGE
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def find_gesture(lemma: str, *, language: str = "kk-KZ", db_path: str | Path | None = None) -> dict[str, Any] | None:
    query = tuple(normalize_text(lemma))
    if not query:
        return None
    normalized_query = " ".join(query)
    with connect(db_path) as db:
        # Resolve labels first, then inspect only clips belonging to exact
        # matches. Loading every clip's JSON for every input token scales
        # poorly once a real vocabulary (hundreds/thousands of signs) is used.
        labels = db.execute(
            "SELECT id, lemma, phrase FROM gestures WHERE language=?",
            (language,),
        ).fetchall()
        phrase_ids = [int(row[0]) for row in labels
                      if row[2] and tuple(normalize_text(row[2])) == query]
        lemma_ids = [int(row[0]) for row in labels
                     if tuple(normalize_text(row[1])) == query]
        alias = db.execute(
            "SELECT gesture_id FROM gesture_aliases WHERE language=? AND normalized=?",
            (language, normalized_query),
        ).fetchone()

        # Resolve lexical identity before checking clip quality. Never fall
        # through from a specific phrase to an unrelated lemma match just
        # because its recording has better tracking coverage.
        exact_phrase_ids = sorted(set(phrase_ids))
        if len(exact_phrase_ids) > 1:
            return None
        if exact_phrase_ids:
            gesture_id = exact_phrase_ids[0]
        elif alias:
            gesture_id = int(alias[0])
        else:
            exact_lemma_ids = sorted(set(lemma_ids))
            # A lemma can legitimately have multiple phrase-level entries;
            # without a phrase or curated alias, selecting the newest video is
            # not a translation decision.
            if len(exact_lemma_ids) != 1:
                return None
            gesture_id = exact_lemma_ids[0]

        candidates = db.execute(
            """SELECT g.id, g.lemma, g.phrase, g.language, c.id, c.fps,
                      c.frame_count, c.feature_count, c.metadata_json,
                      c.source_video, c.start_frame, c.end_frame, c.landmarks_zlib
               FROM gestures g JOIN motion_clips c ON c.gesture_id=g.id
               WHERE g.id=? ORDER BY c.created_at DESC, c.id DESC""",
            (gesture_id,),
        ).fetchall()
        eligible_candidates = [candidate for candidate in candidates
                               if clip_tracking_eligible(candidate[8])]
        def playback_quality(candidate: tuple[Any, ...]) -> tuple[bool, float, float, float, int]:
            try:
                metadata = json.loads(candidate[8] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            def coverage(name: str) -> float:
                try:
                    value = float(metadata.get(name) or 0.0)
                    return value if math.isfinite(value) else 0.0
                except (TypeError, ValueError):
                    return 0.0

            body_coverage = coverage("body_pose_coverage")
            hand_coverage = coverage("hand_detection_coverage")
            face_coverage = coverage("face_detection_coverage")
            return (
                body_coverage >= 0.5, body_coverage, hand_coverage,
                face_coverage, int(candidate[4]),
            )
        row = max(eligible_candidates, key=playback_quality) if eligible_candidates else None
    if row is None:
        return None
    return {
        "gesture_id": row[0], "lemma": row[1], "phrase": row[2], "language": row[3],
        "clip_id": row[4], "fps": row[5], "frame_count": row[6],
        "feature_count": row[7], "source_video": row[9],
        "start_frame": row[10], "end_frame": row[11],
        "sequence": _unpack_motion(row[12]),
        "metadata": json.loads(row[8]),
    }


def library_stats(db_path: str | Path | None = None) -> dict[str, int]:
    """Return searchable unique motion counts, plus raw storage counts.

    A DB row is not necessarily a usable recording: imports may leave legacy
    duplicates, and clips with poor hand tracking are intentionally excluded
    from playback and matching. Keep the UI's primary counts aligned with
    ``library_coverage`` and expose raw counts separately for diagnostics.
    """
    with connect(db_path) as db:
        stored_gestures = int(db.execute("SELECT COUNT(*) FROM gestures").fetchone()[0])
        stored_clips = int(db.execute("SELECT COUNT(*) FROM motion_clips").fetchone()[0])
        source_rows = db.execute(
            "SELECT id, source_video, metadata_json FROM motion_clips"
        ).fetchall()
    # A source may be represented by a relative path in legacy metadata, an
    # absolute path in a later import, and a SHA-256 on the raw-motion record.
    # Union those aliases so these rows count as one source, including copies
    # at different paths when their content digest matches.
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for clip_id, source_video, metadata_json in source_rows:
        try:
            metadata = json.loads(metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        aliases = []
        if source_video:
            path = Path(source_video).expanduser()
            if not path.is_absolute():
                path = Path(config.BASE_DIR) / path
            try:
                aliases.append(f"path:{path.resolve().as_posix().casefold()}")
            except (OSError, RuntimeError):
                aliases.append(f"path:{str(source_video).replace(chr(92), '/').casefold()}")
        digest = metadata.get("source_video_sha256")
        if digest:
            aliases.append(f"sha256:{str(digest).casefold()}")
        if not aliases:
            aliases.append(f"clip:{clip_id}")
        for alias in aliases[1:]:
            union(aliases[0], alias)
        find(aliases[0])
    unique_sources = len({find(value) for value in parent})
    coverage = library_coverage(db_path)
    return {
        "gestures": sum(item["gestures"] for item in coverage),
        "clips": sum(item["eligible_clips"] for item in coverage),
        "stored_gestures": stored_gestures,
        "stored_clips": stored_clips,
        "unique_sources": unique_sources,
    }


def available_search_terms(
    language: str = "kk-KZ", db_path: str | Path | None = None
) -> list[str]:
    """Return exact labels/curated aliases searchable in a language with usable clips."""
    terms: set[str] = set()
    with connect(db_path) as db:
        labels = db.execute(
            """SELECT g.lemma, g.phrase, c.metadata_json
               FROM gestures g JOIN motion_clips c ON c.gesture_id=g.id
               WHERE g.language=?""",
            (language,),
        ).fetchall()
        aliases = db.execute(
            """SELECT a.alias, c.metadata_json
               FROM gesture_aliases a
               JOIN motion_clips c ON c.gesture_id=a.gesture_id
               WHERE a.language=?""",
            (language,),
        ).fetchall()
    for lemma, phrase, metadata in labels:
        if not clip_tracking_eligible(metadata):
            continue
        for term in (lemma, phrase):
            if term and term.strip():
                terms.add(term.strip())
    for alias, metadata in aliases:
        if alias and alias.strip() and clip_tracking_eligible(metadata):
            terms.add(alias.strip())
    return sorted(terms, key=lambda value: (value.casefold(), value))


def library_coverage(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Summarize usable vocabulary and independent recordings for each language."""
    with connect(db_path) as db:
        label_rows = db.execute(
            "SELECT language, lemma FROM gestures ORDER BY language, lemma"
        ).fetchall()
        rows = db.execute(
            """SELECT g.language, g.lemma, c.id, c.signer_id, c.source_video,
                      c.start_frame, c.end_frame, c.metadata_json
               FROM gestures g JOIN motion_clips c ON c.gesture_id=g.id
               ORDER BY g.language, g.lemma, c.id"""
        ).fetchall()

    coverage: dict[str, dict[str, Any]] = {}
    for language, lemma in label_rows:
        item = coverage.setdefault(language, {
            "language": language,
            "catalog_gestures": set(),
            "gestures": set(),
            "recordings": set(),
            "recording_aliases": {},
            "source_group_aliases": {},
            "validation_groups": set(),
            "body_pose_recordings": set(),
        })
        item["catalog_gestures"].add(lemma)
    for language, lemma, clip_id, signer_id, source_video, start_frame, end_frame, metadata_json in rows:
        item = coverage.setdefault(language, {
            "language": language,
            "catalog_gestures": set(),
            "gestures": set(),
            "recordings": set(),
            "recording_aliases": {},
            "source_group_aliases": {},
            "validation_groups": set(),
            "body_pose_recordings": set(),
        })
        try:
            metadata = json.loads(metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not clip_tracking_eligible(metadata):
            continue
        item["gestures"].add(lemma)
        # A recording copied to another path (or recorded before hashes were
        # added) is still one example. Fall back to canonical path plus clip
        # boundaries for legacy rows without a content digest.
        source_hash = metadata.get("source_video_sha256")
        source_aliases = []
        if source_video:
            try:
                canonical_path = str(Path(source_video).expanduser().resolve()).casefold()
            except (OSError, RuntimeError):
                canonical_path = str(source_video).replace("\\", "/").casefold()
            source_aliases.append(f"path:{canonical_path}")
        if source_hash:
            source_aliases.append(f"sha256:{source_hash}")
        if source_aliases:
            aliases = [(lemma, alias, start_frame, end_frame) for alias in source_aliases]
            recording = next(
                (item["recording_aliases"][alias] for alias in aliases
                 if alias in item["recording_aliases"]),
                aliases[0],
            )
            for alias in aliases:
                item["recording_aliases"][alias] = recording
        else:
            recording = (lemma, f"clip:{clip_id}", start_frame, end_frame)
        item["recordings"].add(recording)
        source_group = None
        if source_aliases:
            source_group = next(
                (item["source_group_aliases"][alias] for alias in source_aliases
                 if alias in item["source_group_aliases"]),
                source_aliases[0],
            )
            for alias in source_aliases:
                item["source_group_aliases"][alias] = source_group
        group = (f"signer:{signer_id}" if signer_id else
                 f"video:{source_group}" if source_group else f"clip:{clip_id}")
        item["validation_groups"].add(group)
        if metadata.get("body_pose_coverage", 0) >= 0.5:
            item["body_pose_recordings"].add(recording)

    return [
        {
            "language": language,
            "catalog_gestures": len(item["catalog_gestures"]),
            "gestures": len(item["gestures"]),
            "uncovered_gestures": sorted(item["catalog_gestures"] - item["gestures"]),
            "eligible_clips": len(item["recordings"]),
            "validation_groups": len(item["validation_groups"]),
            "body_pose_clips": len(item["body_pose_recordings"]),
        }
        for language, item in sorted(coverage.items())
    ]


def load_motion_library(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Возвращает motion-клипы с метками и распакованными последовательностями."""
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT c.id, g.lemma, g.phrase, g.language, c.fps, c.frame_count,
                      c.feature_count, c.source_video, c.start_frame, c.end_frame,
                      c.metadata_json, c.landmarks_zlib
               FROM motion_clips c JOIN gestures g ON g.id=c.gesture_id
               ORDER BY c.created_at DESC, c.id DESC"""
        ).fetchall()
    clips = []
    for row in rows:
        try:
            metadata = json.loads(row[10])
            sequence = _unpack_motion(row[11])
        except (TypeError, json.JSONDecodeError, ValueError, zlib.error):
            continue
        clips.append({
            "clip_id": int(row[0]), "lemma": row[1], "phrase": row[2],
            "language": row[3], "fps": float(row[4]),
            "frame_count": int(row[5]), "feature_count": int(row[6]),
            "source_video": row[7], "start_frame": int(row[8]),
            "end_frame": int(row[9]) if row[9] is not None else None,
            "metadata": metadata,
            "sequence": sequence,
        })
    return clips


def get_motion_clip(clip_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Load one exact persisted clip without decompressing the whole library."""
    with connect(db_path) as db:
        row = db.execute(
            """SELECT c.id, g.lemma, g.phrase, g.language, c.fps, c.frame_count,
                      c.feature_count, c.source_video, c.start_frame, c.end_frame,
                      c.metadata_json, c.landmarks_zlib
               FROM motion_clips c JOIN gestures g ON g.id=c.gesture_id
               WHERE c.id=?""",
            (int(clip_id),),
        ).fetchone()
    if row is None:
        return None
    try:
        metadata = json.loads(row[10] or "{}")
        sequence = _unpack_motion(row[11])
    except (TypeError, json.JSONDecodeError, ValueError, zlib.error):
        return None
    return {
        "clip_id": int(row[0]), "lemma": row[1], "phrase": row[2],
        "language": row[3], "fps": float(row[4]),
        "frame_count": int(row[5]), "feature_count": int(row[6]),
        "source_video": row[7], "start_frame": int(row[8]),
        "end_frame": int(row[9]) if row[9] is not None else None,
        "metadata": metadata, "sequence": sequence,
    }


def normalize_text(text: str) -> list[str]:
    """Разбивает русско-казахский текст на безопасные токены для поиска."""
    return [token for token in re.findall(r"[\wӘәҒғҚқҢңӨөҰұҮүҺһІіЁёА-Яа-я]+", text.lower()) if token]


def compose_phrase(text: str, *, language: str = "kk-KZ", gap_frames: int = 4,
                   db_path: str | Path | None = None) -> tuple[np.ndarray, list[str], list[str]]:
    """Собирает клипы по самой длинной точной фразе или отдельным словам.

    Возвращает (sequence, found_words, missing_words). Между найденными клипами
    вставляется короткий пустой промежуток (нулевые landmarks), а не
    синтезированная интерполяция между двумя разными жестами. Для точного
    воспроизведения клипов с их исходным FPS используйте compose_phrase_segments().
    """
    segments, found, missing = compose_phrase_segments(text, language=language, db_path=db_path)
    clips = [segment["sequence"] for segment in segments if segment["type"] == "motion"]
    if not clips:
        return np.zeros((0, config.TOTAL_FEATURES), dtype=np.float32), found, missing
    assembled: list[np.ndarray] = [clips[0]]
    for previous, current in zip(clips, clips[1:]):
        if gap_frames > 0:
            # Never invent wrist/finger/face trajectories between independent
            # source recordings. Zero rows represent an explicit tracking gap.
            assembled.append(np.zeros((gap_frames, current.shape[1]), dtype=np.float32))
        assembled.append(current)
    return np.concatenate(assembled, axis=0), found, missing


def compose_phrase_segments(text: str, *, language: str = "kk-KZ",
                            db_path: str | Path | None = None) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Разбирает текст по порядку, сохраняя FPS клипов и неизвестные слова."""
    tokens = normalize_text(text)
    found: list[str] = []
    missing: list[str] = []
    segments: list[dict[str, Any]] = []
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT DISTINCT g.lemma, g.phrase FROM gestures g
               JOIN motion_clips c ON c.gesture_id=g.id WHERE g.language=?""",
            (language,),
        ).fetchall()
    key_to_lemma: dict[tuple[str, ...], str] = {}
    for lemma, phrase in rows:
        for label in (phrase, lemma):
            key = tuple(normalize_text(label or ""))
            if key:
                key_to_lemma.setdefault(key, lemma)
    with connect(db_path) as db:
        alias_rows = db.execute(
            """SELECT DISTINCT a.alias, g.lemma FROM gesture_aliases a
               JOIN gestures g ON g.id=a.gesture_id
               JOIN motion_clips c ON c.gesture_id=g.id
               WHERE a.language=?""",
            (language,),
        ).fetchall()
    for alias, lemma in alias_rows:
        key = tuple(normalize_text(alias))
        if key:
            key_to_lemma.setdefault(key, lemma)
    keys = sorted(key_to_lemma, key=len, reverse=True)
    cursor = 0
    while cursor < len(tokens):
        matched: tuple[str, ...] | None = None
        gesture = None
        for key in keys:
            if tokens[cursor:cursor + len(key)] != list(key):
                continue
            gesture = find_gesture(" ".join(key), language=language, db_path=db_path)
            if gesture is not None:
                matched = key
                break
        if matched is None or gesture is None:
            token = tokens[cursor]
            missing.append(token)
            segments.append({"type": "missing", "label": token})
            cursor += 1
            continue
        label = " ".join(matched)
        found.append(label)
        segments.append({
            "type": "motion", "label": label,
            "sequence": np.asarray(gesture["sequence"], dtype=np.float32),
            "fps": float(gesture["fps"]), "clip_id": int(gesture["clip_id"]),
            "source_video": gesture["source_video"],
            "start_frame": gesture["start_frame"], "end_frame": gesture["end_frame"],
            "metadata": gesture["metadata"],
        })
        cursor += len(matched)
    return segments, found, missing

