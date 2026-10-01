"""Независимые от ML-бэкенда функции подготовки обучения и проверки данных."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from src.normalize import PREPROCESSING_VERSION


def save_label_map(
    label_map: dict[str, int],
    path: str | Path,
    *,
    training_metadata: dict | None = None,
) -> None:
    """Store labels, preprocessing compatibility and the model's validation provenance."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        json.dump({
            "preprocessing_version": PREPROCESSING_VERSION,
            "labels": label_map,
            "training": training_metadata,
        }, stream, ensure_ascii=False, indent=2)


def load_label_map(path: str | Path) -> dict[int, str]:
    """Loads a compatible map as {class_index: label}; rejects unversioned maps."""
    with Path(path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if (not isinstance(payload, dict)
            or payload.get("preprocessing_version") != PREPROCESSING_VERSION
            or not isinstance(payload.get("labels"), dict)):
        raise ValueError(
            "Файл меток создан для другой/неизвестной нормализации. "
            "Переобучите модель текущим конвейером."
        )
    result: dict[int, str] = {}
    for label, index in payload["labels"].items():
        result[int(index)] = str(label)
    return result


def stratified_split_indices(
    labels: np.ndarray, validation_split: float, *, seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Возвращает непересекающиеся стратифицированные train/validation индексы."""
    labels = np.asarray(labels)
    if labels.ndim != 1:
        raise ValueError("Метки должны иметь форму (samples,)")
    if not 0.0 < validation_split < 1.0:
        raise ValueError("validation_split должен быть между 0 и 1")
    classes, counts = np.unique(labels, return_counts=True)
    too_small = {str(label): int(count) for label, count in zip(classes, counts) if count < 2}
    if too_small:
        raise ValueError(f"Нужно минимум 2 независимых видео на класс: {too_small}")
    rng = np.random.default_rng(seed)
    train_indices: list[int] = []
    validation_indices: list[int] = []
    for label in classes:
        indices = rng.permutation(np.flatnonzero(labels == label))
        validation_count = max(1, int(round(len(indices) * validation_split)))
        validation_count = min(validation_count, len(indices) - 1)
        validation_indices.extend(indices[:validation_count].tolist())
        train_indices.extend(indices[validation_count:].tolist())
    return rng.permutation(train_indices), rng.permutation(validation_indices)


def grouped_split_indices(
    labels: np.ndarray,
    groups: np.ndarray,
    validation_split: float,
    *,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Split by signer/source groups so related recordings never leak across sets."""
    labels = np.asarray(labels)
    groups = np.asarray(groups, dtype=str)
    if labels.ndim != 1 or groups.ndim != 1 or len(labels) != len(groups):
        raise ValueError("Метки и группы должны быть одномерными массивами одинаковой длины")
    if not 0.0 < validation_split < 1.0:
        raise ValueError("validation_split должен быть между 0 и 1")
    classes = np.unique(labels)
    group_labels = {group: set(labels[groups == group].tolist()) for group in np.unique(groups)}
    insufficient = [
        str(label) for label in classes
        if len({group for group, member_labels in group_labels.items() if label in member_labels}) < 2
    ]
    if insufficient:
        raise ValueError(
            "Для независимой проверки нужны минимум 2 исполнителя/источника на класс: "
            + ", ".join(insufficient)
        )

    rng = np.random.default_rng(seed)
    candidates = list(group_labels)
    rng.shuffle(candidates)
    selected: set[str] = set()

    def preserves_training_class(group: str) -> bool:
        for label in classes:
            class_groups = {item for item, member_labels in group_labels.items() if label in member_labels}
            if label in group_labels[group] and len(class_groups - selected - {group}) < 1:
                return False
        return True

    # First ensure every class has held-out data, choosing shared groups where possible.
    while any(not any(label in group_labels[group] for group in selected) for label in classes):
        uncovered = [label for label in classes
                     if not any(label in group_labels[group] for group in selected)]
        possible = [group for group in candidates if group not in selected
                    and any(label in group_labels[group] for label in uncovered)
                    and preserves_training_class(group)]
        if not possible:
            raise ValueError("Не удалось выделить группы validation без потери классов в train")
        possible.sort(key=lambda group: -sum(label in group_labels[group] for label in uncovered))
        selected.add(possible[0])

    target_validation = max(len(classes), int(round(len(labels) * validation_split)))
    for group in candidates:
        if sum(np.count_nonzero(groups == item) for item in selected) >= target_validation:
            break
        if group not in selected and preserves_training_class(group):
            selected.add(group)

    validation_indices = np.flatnonzero(np.isin(groups, list(selected)))
    train_indices = np.flatnonzero(~np.isin(groups, list(selected)))
    if set(np.unique(labels[train_indices])) != set(classes) or set(np.unique(labels[validation_indices])) != set(classes):
        raise ValueError("Групповое разбиение не сохранило все классы в train и validation")
    return rng.permutation(train_indices), rng.permutation(validation_indices)
