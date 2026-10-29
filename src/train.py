"""
train.py — Скрипт обучения модели распознавания жестов КЖЯ

КАК ЭТО РАБОТАЕТ (для защиты перед жюри):
===========================================

Обучение нейросети — это процесс, в котором модель «смотрит» на примеры
жестов и постепенно учится их различать. Это похоже на то, как ученик
учится решать задачи: сначала делает ошибки, потом учитывает их и улучшается.

Ключевые понятия:

EPOCH (эпоха):
    Одна эпоха = модель ОДИН РАЗ «прочитала» все обучающие данные.
    Если у нас 100 видео жестов и мы обучаем 50 эпох — модель
    «посмотрит» каждое видео 50 раз. С каждой эпохой модель
    становится чуть точнее (как ученик, который перечитывает учебник).

BATCH_SIZE (размер батча):
    Сколько примеров модель обрабатывает ЗА ОДИН РАЗ.
    batch_size=16 означает: берём 16 видео, вычисляем ошибку
    по всем 16, обновляем веса. Потом берём следующие 16 и т.д.
    
    Почему не по одному? Это было бы слишком «нервным» — модель
    дёргалась бы из-за каждого примера. 16 примеров дают более
    стабильный сигнал для обучения.

VALIDATION_SPLIT (валидационная выборка):
    Мы отделяем 20% данных и НЕ обучаем на них модель.
    Эти 20% используются только для ПРОВЕРКИ: «а может ли модель
    распознать жесты, которые она НЕ ВИДЕЛА при обучении?»
    
    Это как контрольная работа в школе: учитель проверяет,
    ПОНЯЛ ли ученик материал, а не ЗАЗУБРИЛ.

EARLY STOPPING (ранняя остановка):
    Если модель перестала улучшаться на валидационных данных
    в течение 10 эпох подряд — мы останавливаем обучение.
    Это экономит время и предотвращает переобучение.
    
    restore_best_weights=True — после остановки возвращаемся
    к ЛУЧШЕМУ состоянию модели (а не к последнему).

MODEL CHECKPOINT (контрольная точка):
    Автоматически сохраняет модель каждый раз, когда она
    показывает ЛУЧШИЙ результат на валидации. Даже если
    потом модель станет хуже — у нас останется лучшая версия.
"""

import os
import sys

# Добавляем корневую папку проекта в путь импорта
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import config

# Импорт TensorFlow и компонентов обучения
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

# Импорт наших модулей
from src.model import create_model
from src.normalize import generate_augmented_dataset
from src.training_utils import grouped_split_indices, save_label_map, stratified_split_indices


def train_model(X: np.ndarray,
                y: np.ndarray,
                num_classes: int,
                epochs: int = 50,
                batch_size: int = 16,
                validation_split: float = 0.2,
                augment_factor: int = 1,
                groups: np.ndarray | None = None,
                checkpoint_dir: str | None = None) -> tuple:
    """
    Обучает модель распознавания жестов.

    Процесс обучения:
        1. Проверяем и при необходимости генерируем синтетическую аугментацию.
        2. Разделяем данные: 80% для обучения, 20% для валидации.
        3. Создаём модель через create_model().
        4. Настраиваем callbacks (EarlyStopping, ModelCheckpoint).
        5. Запускаем обучение (model.fit).
        6. Возвращаем обученную модель и историю обучения.

    Аргументы:
        X (np.ndarray): Входные данные, форма (N, 30, 162).
        y (np.ndarray): Метки классов, форма (N,).
        num_classes (int): Количество различных жестов.
        epochs (int): Максимальное количество эпох обучения.
        batch_size (int): Количество примеров в одном батче.
        validation_split (float): Доля данных для валидации (0.2 = 20%).
        augment_factor (int): Коэффициент аугментации данных (1 = без аугментации, 3 = ×3 раз).

    Возвращает:
        tuple: (model, history)
    """
    print(f"\n{'=' * 60}")
    print(f"ОБУЧЕНИЕ МОДЕЛИ")
    print(f"{'=' * 60}")
    print(f"  Исходных примеров:      {X.shape[0]}")
    print(f"  Форма входа:           {X.shape}")
    print(f"  Количество классов:    {num_classes}")
    print(f"  Аугментация данных:    {f'×{augment_factor}' if augment_factor > 1 else 'Отключена'}")
    print(f"  Эпох (максимум):       {epochs}")
    print(f"  Размер батча:          {batch_size}")
    print(f"  Валидационная выборка: {validation_split * 100:.0f}%")

    if X.shape[0] == 0:
        print("[ОШИБКА] Нет обучающих данных!")
        return None, None

    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int64)
    if X.ndim != 3 or len(y) != len(X):
        raise ValueError(f"Ожидаются X=(samples,frames,features) и y=(samples,), получено {X.shape}, {y.shape}")
    if not np.isfinite(X).all():
        raise ValueError("Обучающий датасет содержит NaN или бесконечные значения")
    classes, counts = np.unique(y, return_counts=True)
    if len(classes) != num_classes:
        raise ValueError(f"Передано классов {num_classes}, но в y найдено {len(classes)}")
    if not np.array_equal(classes, np.arange(num_classes)):
        raise ValueError(f"Метки классов должны быть последовательными от 0 до {num_classes - 1}")
    # Стратифицируем до аугментации: каждый класс присутствует в validation,
    # а синтетические варианты не могут утечь из train в validation.
    if groups is None:
        train_indices, validation_indices = stratified_split_indices(y, validation_split)
    else:
        train_indices, validation_indices = grouped_split_indices(y, groups, validation_split)
    X_train, y_train = X[train_indices], y[train_indices]
    X_validation, y_validation = X[validation_indices], y[validation_indices]

    # Аугментируем только обучающую часть после разбиения.
    if augment_factor > 1:
        X_train, y_train = generate_augmented_dataset(X_train, y_train, factor=augment_factor)
        print(f"  Примеров train после аугментации: {X_train.shape[0]}")

    print(f"  Train-примеров:        {len(X_train)}")
    print(f"  Validation-примеров:   {len(X_validation)}")
    print(f"{'=' * 60}\n")

    # ============================================================
    # Шаг 1: Проверка данных
    # ============================================================

    if X_train.shape[0] < 10:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Очень мало данных ({X_train.shape[0]} train-примеров).")
        print(f"  Для хорошего обучения рекомендуется минимум 50 примеров на класс.\n")

    # ============================================================
    # Шаг 2: Создание модели
    # ============================================================
    model = create_model(
        num_classes=num_classes,
        sequence_length=X_train.shape[1],
        num_features=X_train.shape[2]
    )

    # ============================================================
    # Шаг 3: Настройка callbacks
    # ============================================================
    # Создаём папку для моделей, если её нет
    checkpoint_directory = checkpoint_dir or config.MODELS_DIR
    os.makedirs(checkpoint_directory, exist_ok=True)

    # Путь к лучшей модели
    best_model_path = os.path.join(checkpoint_directory, "best_model.h5")

    callbacks = [
        # EarlyStopping — остановка, если модель не улучшается.
        # patience=10 — ждём 10 эпох. Если за 10 эпох val_loss
        # не уменьшилась — значит, дальше обучать бесполезно.
        # restore_best_weights=True — после остановки возвращаемся
        # к весам, которые дали ЛУЧШИЙ результат.
        EarlyStopping(
            monitor="val_loss",       # Следим за ошибкой на валидации
            patience=10,              # Ждём 10 эпох без улучшения
            restore_best_weights=True,  # Восстанавливаем лучшие веса
            verbose=1                 # Выводим сообщение при срабатывании
        ),

        # ModelCheckpoint — автоматическое сохранение лучшей модели.
        # Каждый раз, когда val_loss становится ниже предыдущего
        # рекорда, модель сохраняется в файл.
        ModelCheckpoint(
            filepath=best_model_path,
            monitor="val_loss",
            save_best_only=True,      # Сохраняем ТОЛЬКО если результат лучший
            verbose=1
        ),
    ]

    print(f"  Callbacks настроены:")
    print(f"    - EarlyStopping (patience=10)")
    print(f"    - ModelCheckpoint -> {best_model_path}\n")

    # ============================================================
    # Шаг 4: Обучение модели
    # ============================================================
    print("Начинаю обучение...\n")

    try:
        history = model.fit(
            X_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=(X_validation, y_validation),
            callbacks=callbacks,
            verbose=1  # Прогресс-бар для каждой эпохи
        )
    except Exception as e:
        print(f"\n[ОШИБКА] Обучение прервано: {type(e).__name__}: {e}")
        return None, None

    # ============================================================
    # Шаг 5: Итоги обучения
    # ============================================================
    final_acc = history.history["accuracy"][-1]
    final_val_acc = history.history["val_accuracy"][-1]
    final_loss = history.history["loss"][-1]
    final_val_loss = history.history["val_loss"][-1]
    total_epochs = len(history.history["accuracy"])

    print(f"\n{'=' * 60}")
    print(f"ОБУЧЕНИЕ ЗАВЕРШЕНО")
    print(f"{'=' * 60}")
    print(f"  Эпох пройдено:            {total_epochs}")
    print(f"  Точность (обучение):       {final_acc:.4f} ({final_acc * 100:.1f}%)")
    print(f"  Точность (валидация):      {final_val_acc:.4f} ({final_val_acc * 100:.1f}%)")
    print(f"  Ошибка (обучение):         {final_loss:.4f}")
    print(f"  Ошибка (валидация):        {final_val_loss:.4f}")
    print(f"{'=' * 60}\n")

    # Предупреждение о переобучении
    if final_acc - final_val_acc > 0.15:
        print("[ПРЕДУПРЕЖДЕНИЕ] Возможно переобучение!")
        print(f"  Разница accuracy: {(final_acc - final_val_acc) * 100:.1f}%")
        print(f"  Рекомендации: увеличить Dropout, добавить данные, или уменьшить модель.\n")

    return model, history


def save_model_and_labels(model: tf.keras.Model,
                          label_map: dict,
                          model_path: str = None,
                          map_path: str = None,
                          training_metadata: dict | None = None) -> None:
    """
    Сохраняет обученную модель и маппинг меток.

    Сохраняем два файла:
        1. sign_model.h5 — веса и архитектура нейросети (бинарный формат HDF5).
        2. label_map.json — словарь {название_жеста: числовой_код} (текстовый JSON).

    Зачем сохранять label_map?
        Модель работает с ЧИСЛАМИ (0, 1, 2...), а не с названиями жестов.
        label_map нужен, чтобы превратить число обратно в название:
        модель выдала «2» → label_map говорит «2 = пожалуйста».

    Аргументы:
        model: Обученная модель Keras.
        label_map (dict): Словарь {название: число}. Пример: {"privet": 0, "spasibo": 1}.
        model_path (str): Путь для сохранения модели.
        map_path (str): Путь для сохранения маппинга меток.
    """
    if model_path is None:
        model_path = os.path.join(config.MODELS_DIR, "sign_model.h5")
    if map_path is None:
        map_path = os.path.join(config.MODELS_DIR, "label_map.json")

    # Создаём папку, если нет
    os.makedirs(os.path.dirname(model_path), exist_ok=True)

    try:
        # Сохраняем модель
        model.save(model_path)
        print(f"[OK] Модель сохранена: {model_path}")

        # Сохраняем метки с версией нормализации, чтобы не применять веса
        # к несовместимой системе признаков.
        save_label_map(label_map, map_path, training_metadata=training_metadata)
        print(f"[OK] Маппинг меток сохранён: {map_path}")

    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить: {e}")
        raise
        raise


def plot_history(history) -> None:
    """
    Строит графики обучения: точность (accuracy) и ошибку (loss).

    Два графика показывают, КАК модель училась:
        - Accuracy (точность): доля правильных ответов. Должна расти.
        - Loss (ошибка): мера «неправильности» предсказаний. Должна падать.

    На каждом графике ДВЕ линии:
        - Training (синяя) — результат на обучающих данных.
        - Validation (оранжевая) — результат на валидационных данных.

    Если линии расходятся (training хорошо, validation плохо) —
    это ПЕРЕОБУЧЕНИЕ. Модель «зазубрила» обучающие данные.

    Аргументы:
        history: Объект History из model.fit().

    Возвращает:
        matplotlib.figure.Figure: Фигура с графиками (можно показать в Streamlit).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Без GUI, для серверов и скриптов
        import matplotlib.pyplot as plt
    except ImportError:
        print("[ОШИБКА] matplotlib не установлен. Установите: pip install matplotlib")
        return None

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- График 1: Accuracy (точность) ---
    axes[0].plot(history.history["accuracy"], label="Обучение", linewidth=2)
    axes[0].plot(history.history["val_accuracy"], label="Валидация", linewidth=2)
    axes[0].set_title("Точность модели (Accuracy)", fontsize=14)
    axes[0].set_xlabel("Эпоха")
    axes[0].set_ylabel("Accuracy")
    axes[0].legend(fontsize=12)
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim([0, 1.05])

    # --- График 2: Loss (ошибка) ---
    axes[1].plot(history.history["loss"], label="Обучение", linewidth=2)
    axes[1].plot(history.history["val_loss"], label="Валидация", linewidth=2)
    axes[1].set_title("Ошибка модели (Loss)", fontsize=14)
    axes[1].set_xlabel("Эпоха")
    axes[1].set_ylabel("Loss")
    axes[1].legend(fontsize=12)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()

    # Сохраняем графики в файл
    docs_dir = os.path.join(config.BASE_DIR, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    graph_path = os.path.join(docs_dir, "training_graphs.png")

    try:
        fig.savefig(graph_path, dpi=150, bbox_inches="tight")
        print(f"[OK] Графики сохранены: {graph_path}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить графики: {e}")

    return fig


# ============================================================
# Точка входа — демонстрация обучения на синтетических данных
# ============================================================
if __name__ == "__main__":
    """
    Запуск: python src/train.py
    
    Демонстрация обучения на СЛУЧАЙНЫХ данных.
    В реальном проекте данные берутся из extract_landmarks.py + normalize.py.
    """
    print("=== Демонстрация обучения модели ===\n")
    print("ВНИМАНИЕ: Используются СЛУЧАЙНЫЕ данные для демонстрации.")
    print("В реальном проекте используйте данные из extract_landmarks.py\n")

    # Создаём синтетические данные
    np.random.seed(42)
    num_classes = 3
    num_samples = 60  # 20 примеров на класс

    # X — случайные координаты, форма (60, 30, 63)
    X = np.random.rand(num_samples, config.SEQUENCE_LENGTH,
                       config.NUM_LANDMARKS * config.COORDS_PER_LANDMARK)

    # y — метки: 20 × класс0, 20 × класс1, 20 × класс2
    y = np.array([i // 20 for i in range(num_samples)])

    # Перемешиваем данные
    shuffle_idx = np.random.permutation(num_samples)
    X = X[shuffle_idx]
    y = y[shuffle_idx]

    # Обучаем (мало эпох для быстрой демонстрации)
    model, history = train_model(
        X, y,
        num_classes=num_classes,
        epochs=10,
        batch_size=8,
        validation_split=0.2
    )

    if model is not None:
        # Сохраняем модель
        label_map = {"privet": 0, "spasibo": 1, "da": 2}
        save_model_and_labels(model, label_map)

        # Строим графики
        fig = plot_history(history)

        print("\n=== Демонстрация завершена ===")
    else:
        print("\n[ОШИБКА] Обучение не удалось.")
