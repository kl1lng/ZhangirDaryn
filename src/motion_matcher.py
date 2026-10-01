"""Сравнение последовательности с motion-примерами SQLite-библиотеки.

Это nearest-example режим, а не обученный классификатор: результат показывает
только ближайший сохранённый клип и расстояние до него.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

import config
from src.motion_db import clip_tracking_eligible, load_motion_library
from src.normalize import normalize_sequence


def _resample(sequence: np.ndarray, frames: int) -> np.ndarray:
    """Равномерно пересэмплирует временную ось с линейной интерполяцией."""
    sequence = np.asarray(sequence, dtype=np.float32)
    if sequence.ndim != 2 or not len(sequence):
        raise ValueError("Для сравнения нужна непустая последовательность кадров")
    if len(sequence) == frames:
        return sequence.copy()
    if len(sequence) == 1:
        return np.repeat(sequence, frames, axis=0)
    positions = np.linspace(0, len(sequence) - 1, frames)
    lower = np.floor(positions).astype(int)
    upper = np.minimum(lower + 1, len(sequence) - 1)
    weight = (positions - lower)[:, None]
    return sequence[lower] * (1.0 - weight) + sequence[upper] * weight


def _as_full_features(sequence: np.ndarray) -> np.ndarray:
    """Приводит старые 126-признаковые клипы к текущему формату из 162."""
    array = np.asarray(sequence, dtype=np.float32)
    if array.ndim != 2 or not len(array):
        raise ValueError("Motion-клип должен быть двумерной последовательностью")
    if array.shape[1] == config.HAND_FEATURES:
        array = np.pad(array, ((0, 0), (0, config.FACE_FEATURES)))
    if array.shape[1] != config.TOTAL_FEATURES:
        raise ValueError(f"Ожидалось {config.TOTAL_FEATURES} признака на кадр, получено {array.shape[1]}")
    if not np.isfinite(array).all():
        raise ValueError("Последовательность содержит некорректные координаты")
    return array


class MotionLibraryMatcher:
    """Находит ближайший motion-пример; не интерпретирует distance как confidence."""

    def __init__(self, clips: list[dict[str, Any]] | None = None, *, frames: int = 30):
        self.frames = int(frames)
        self.references: list[dict[str, Any]] = []
        seen_sources: set[tuple[tuple[str, str], str]] = set()
        for clip in load_motion_library() if clips is None else clips:
            try:
                if not clip_tracking_eligible(clip.get("metadata")):
                    continue
                raw = _as_full_features(clip["sequence"])
                normalized = normalize_sequence(raw)
                sample = _resample(normalized, self.frames)
            except (KeyError, TypeError, ValueError):
                continue
            # Пропускаем записи без полезных landmarks рук.
            hand = raw[:, :config.HAND_FEATURES]
            if np.count_nonzero(np.any(np.abs(hand) > 1e-6, axis=1)) < 3:
                continue
            source_video = clip.get("source_video")
            if source_video:
                source_path = Path(str(source_video)).expanduser()
                if not source_path.is_absolute():
                    source_path = Path(config.BASE_DIR) / source_path
                source_key = (self._class_key(clip), str(source_path.resolve()).casefold())
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
            self.references.append({**clip, "sample": sample})
        self.class_count = len({self._class_key(reference) for reference in self.references})
        self.can_classify = self.class_count >= 2

    @staticmethod
    def _has_hands(sequence: np.ndarray, start: int = 0, end: int = config.HAND_FEATURES) -> np.ndarray:
        hands = sequence[:, start:end].reshape(-1, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK)
        wrist = hands[:, :1, :2]
        extent = np.linalg.norm(hands[:, 1:, :2] - wrist, axis=-1).max(axis=1)
        return extent > 0.012

    @staticmethod
    def _distance(query: np.ndarray, reference: np.ndarray) -> float:
        """Считает ошибку только по реально наблюдаемым модальностям.

        Пропавшая рука/лицо не должна превращаться в десятки совпавших нулей.
        Если модальность есть только с одной стороны пары, учитываем её как
        пропуск, а не игнорируем.
        """
        costs: list[float] = []
        weights: list[float] = []
        for start, end, weight, visible in (
            (0, 63, 1.0, MotionLibraryMatcher._has_hands),
            (63, 126, 1.0, MotionLibraryMatcher._has_hands),
            (126, 162, 0.35, MotionLibraryMatcher._has_face),
        ):
            q_visible = visible(query, start, end)
            r_visible = visible(reference, start, end)
            both = q_visible & r_visible
            either = q_visible | r_visible
            if np.any(both):
                block_cost = np.abs(query[both, start:end] - reference[both, start:end]).mean()
                costs.append(float(block_cost))
                weights.append(weight)
            if np.any(either & ~both):
                costs.append(0.5)
                weights.append(weight * 0.5)
        return float(np.average(costs, weights=weights)) if weights else float("inf")

    @staticmethod
    def _temporal_distance(query: np.ndarray, reference: np.ndarray) -> float:
        """Сравнивает временную форму жеста с ограниченной DTW-растяжкой.

        Жесты одного языка могут выполняться с разной скоростью. Сравнение
        кадров строго по одинаковым индексам ошибочно считает это разными
        жестами; ограниченная полоса допускает умеренное изменение темпа, но
        не позволяет переставлять начало и конец или сопоставлять произвольные
        фазы клипа.
        """
        if not len(query) or not len(reference):
            return float("inf")
        n, m = len(query), len(reference)
        local_sum = np.zeros((n, m), dtype=np.float64)
        local_weight = np.zeros((n, m), dtype=np.float64)
        for start, end, weight, visible in (
            (0, 63, 1.0, MotionLibraryMatcher._has_hands),
            (63, 126, 1.0, MotionLibraryMatcher._has_hands),
            (126, 162, 0.35, MotionLibraryMatcher._has_face),
        ):
            q_visible = visible(query, start, end)
            r_visible = visible(reference, start, end)
            both = q_visible[:, None] & r_visible[None, :]
            either = q_visible[:, None] | r_visible[None, :]
            if not np.any(either):
                continue
            block = np.abs(query[:, None, start:end] - reference[None, :, start:end]).mean(axis=2)
            local_sum += np.where(both, block * weight, np.where(either, 0.25 * weight, 0.0))
            local_weight += np.where(both, weight, np.where(either, 0.5 * weight, 0.0))
        local = np.divide(local_sum, local_weight, out=np.full_like(local_sum, 0.5), where=local_weight > 0)

        # Sakoe-Chiba-style band relative to normalized clip time; no extreme
        # warps that could make unrelated motion appear similar.
        band = max(2, int(np.ceil(max(n, m) * 0.15)))
        costs = np.full((n + 1, m + 1), np.inf, dtype=np.float64)
        lengths = np.zeros((n + 1, m + 1), dtype=np.int32)
        costs[0, 0] = 0.0
        for i in range(1, n + 1):
            center = (i - 1) * (m - 1) / max(n - 1, 1)
            lower, upper = max(1, int(np.floor(center - band)) + 1), min(m, int(np.ceil(center + band)) + 1)
            for j in range(lower, upper + 1):
                previous = min((costs[i - 1, j - 1], lengths[i - 1, j - 1]),
                               (costs[i - 1, j], lengths[i - 1, j]),
                               (costs[i, j - 1], lengths[i, j - 1]),
                               key=lambda item: item[0])
                if np.isfinite(previous[0]):
                    costs[i, j] = previous[0] + local[i - 1, j - 1]
                    lengths[i, j] = previous[1] + 1
        return float(costs[n, m] / lengths[n, m]) if lengths[n, m] else float("inf")

    @staticmethod
    def _has_face(sequence: np.ndarray, start: int = 126, end: int = 162) -> np.ndarray:
        return np.any(np.abs(sequence[:, start:end]) > 1e-6, axis=1)

    @staticmethod
    def _class_key(reference: dict[str, Any]) -> tuple[str, str]:
        """Phrase is the lexical class when present; otherwise use its lemma."""
        return (
            str(reference.get("language", "kk-KZ")),
            str(reference.get("phrase") or reference.get("lemma", "")).strip().casefold(),
        )

    def match(self, sequence: np.ndarray) -> dict[str, Any] | None:
        """Возвращает ближайший клип, среднее покоординатное расстояние и runner-up."""
        if not self.references:
            return None
        query = _as_full_features(sequence)
        visible_hand_frames = self._has_hands(query)
        if visible_hand_frames.mean() < config.MOTION_MIN_HAND_COVERAGE:
            return None
        query_sample = _resample(normalize_sequence(query), self.frames)
        ranked = []
        for reference in self.references:
            # DTW distance allows realistic tempo variation; it is still a
            # diagnostic distance, not a probability or calibrated confidence.
            distance = self._temporal_distance(query_sample, reference["sample"])
            ranked.append((distance, reference))
        ranked.sort(key=lambda item: item[0])
        distance, best = ranked[0]
        # Другие записи того же жеста — дополнительные примеры, не другие классы.
        second_distance = next(
            (candidate_distance for candidate_distance, candidate in ranked[1:]
             if self._class_key(candidate) != self._class_key(best)),
            None,
        )
        return {
            "clip_id": best["clip_id"],
            "lemma": best["lemma"],
            "phrase": best.get("phrase"),
            "distance": distance,
            "runner_up_distance": second_distance,
            "is_classifiable": self.can_classify,
            "is_trained_classifier": False,
        }
