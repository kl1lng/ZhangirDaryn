"""
normalize.py — Нормализация координат для обучения нейросети

КАК ЭТО РАБОТАЕТ (для защиты перед жюри):
===========================================

После extract_landmarks.py у нас есть координаты кистей и, если модель лица
доступна, ключевые точки лица. Нормализация сохраняет форму пальцев и положение
кистей в кадре: в КЖЯ одинаковая форма у лица и у корпуса может означать разные
жесты.

Мы разделяем локальную форму кисти и её координату-якорь, используя общий
пространственный масштаб для обеих рук:

ШАГ 1: Вычитаем запястье (WRIST, точка 0)
    Запястье — это «якорь» кисти. Если мы вычтем координаты запястья
    из ВСЕХ остальных точек, то запястье станет точкой (0, 0, 0),
    а все остальные точки будут описывать свою позицию ОТНОСИТЕЛЬНО
    запястья. Это отделяет локальную форму от расположения кисти.

    Аналогия: представь, что ты описываешь, где стоит мебель в комнате.
    Вместо GPS-координат ты говоришь «стул в 2 метрах от двери».
    Неважно, где комната — описание остаётся тем же.

ШАГ 2: Общий масштаб кистей и сохранение якоря запястья
    Находим максимальное евклидово расстояние между ЛЮБЫМИ двумя точками
    руки (обычно это расстояние от запястья до кончика среднего пальца).
    Делим координаты обеих рук на общий масштаб и сохраняем положение
    запястья относительно центра кадра в тех же единицах. Масштаб камеры
    нормализуется, но положение и взаимная геометрия рук не стираются.

    Аналогия: рисунок руки на листе A4 и на доске — масштаб нормализуется,
    но координата рисунка на листе остаётся значимой.

ФИКСИРОВАННАЯ ДЛИНА (30 кадров):
    Нейросеть требует, чтобы ВСЕ входные последовательности имели
    ОДИНАКОВУЮ длину. Мы выбрали 30 кадров, потому что:
    - При 30 FPS это ~1 секунда видео — достаточно для одного жеста.
    - Если жест длиннее — берём 30 равномерно распределённых кадров.
    - Если короче — дополняем нулями (padding).

ПОЧЕМУ PADDING НУЛЯМИ — ЭТО НОРМАЛЬНО?
    В Keras есть специальный слой Masking, который «учит» нейросеть
    ИГНОРИРОВАТЬ нулевые кадры. Нейросеть понимает: «после настоящих
    данных идут нули — это пустое место, его не нужно анализировать».
"""

import os
import sys

# Добавляем корневую папку проекта в путь импорта,
# чтобы можно было использовать config.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import config

PREPROCESSING_VERSION = 2


def _normalize_face(face_seq: np.ndarray) -> np.ndarray:
    """Нормализует 36 координат лица относительно опорного центра носа."""
    face_seq = face_seq.copy().astype(np.float64)
    if np.all(face_seq == 0.0) or face_seq.shape[0] == 0:
        return face_seq

    # Центрирование относительно точки носа (столбцы 0, 1, 2)
    nose = face_seq[:, 0:3]
    nose_tiled = np.tile(nose, config.NUM_FACE_LANDMARKS)
    face_seq = face_seq - nose_tiled

    # Масштабирование
    max_dist = np.max(np.abs(face_seq))
    if max_dist > 1e-8:
        face_seq = face_seq / max_dist

    return face_seq


def _hand_scale(hand_seq: np.ndarray) -> float:
    """Наибольший межточечный размер руки во временной последовательности."""
    points = np.asarray(hand_seq, dtype=np.float64).reshape(-1, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK)
    max_distance = 0.0
    for frame in points:
        if np.all(frame == 0.0):
            continue
        delta = frame[:, None, :] - frame[None, :, :]
        max_distance = max(max_distance, float(np.sqrt(np.sum(delta * delta, axis=2)).max()))
    return max_distance


def _normalize_one_hand(hand_seq: np.ndarray, shared_scale: float | None = None) -> np.ndarray:
    """Сохраняет форму и положение руки относительно центра кадра."""
    hand_seq = hand_seq.copy().astype(np.float64)
    num_frames = hand_seq.shape[0]

    # Если рука вообще не присутствует (все нули), возвращаем нули
    if np.all(hand_seq == 0.0) or num_frames == 0:
        return hand_seq

    # ШАГ 1: Центрирование относительно запястья (точка 0)
    wrist = hand_seq[:, 0:3].copy()
    wrist_tiled = np.tile(wrist, config.NUM_LANDMARKS)
    hand_seq = hand_seq - wrist_tiled

    # Один масштаб на обе руки сохраняет их относительный размер и расстояние.
    scale = float(shared_scale) if shared_scale is not None else _hand_scale(hand_seq)
    if scale <= 1e-8:
        return hand_seq
    hand_seq = hand_seq / scale

    # Запястье больше не зануляется: положение каждой точки задано относительно
    # центра кадра, выраженного в единицах того же масштаба кисти.
    valid_frames = np.any(np.abs(hand_seq) > 1e-8, axis=1)
    frame_anchor = wrist - np.array([0.5, 0.5, 0.0])
    hand_seq = hand_seq.reshape(num_frames, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK)
    hand_seq[valid_frames] += frame_anchor[valid_frames, None, :] / scale
    hand_seq = hand_seq.reshape(num_frames, config.NUM_LANDMARKS * config.COORDS_PER_LANDMARK)

    return hand_seq


def normalize_sequence(sequence: np.ndarray) -> np.ndarray:
    """
    Нормализует последовательность координат рук.

    Поддерживает 162 признака (две руки и лицо), 126 (две руки) и 63 (одна рука).

    Аргументы:
        sequence (np.ndarray): Массив формы (N, 162), (N, 126) или (N, 63).

    Возвращает:
        np.ndarray: Нормализованный массив той же формы.
    """
    sequence = sequence.copy().astype(np.float64)
    if sequence.shape[0] == 0:
        return sequence

    num_features = sequence.shape[1]

    if num_features == 162:
        # Полный вектор: 2 руки (126) + лицо (36).
        # Руки имеют общий масштаб и сохраняют положение относительно кадра;
        # лицо нормализуется относительно носа.
        hand_points = sequence[:, :config.HAND_FEATURES].reshape(
            -1, config.NUM_HANDS, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK
        )
        shared_scale = max(
            (_hand_scale(hand_points[:, side].reshape(-1, config.HAND_FEATURES // config.NUM_HANDS))
             for side in range(config.NUM_HANDS)),
            default=0.0,
        )
        left_hand = _normalize_one_hand(sequence[:, :63], shared_scale)
        right_hand = _normalize_one_hand(sequence[:, 63:126], shared_scale)
        face = _normalize_face(sequence[:, 126:162])
        return np.hstack([left_hand, right_hand, face])
    elif num_features == 126:
        # Разделяем на 63 левая + 63 правая
        shared_scale = max(_hand_scale(sequence[:, :63]), _hand_scale(sequence[:, 63:]))
        left_hand = _normalize_one_hand(sequence[:, :63], shared_scale)
        right_hand = _normalize_one_hand(sequence[:, 63:], shared_scale)
        return np.hstack([left_hand, right_hand])
    elif num_features == 63:
        return _normalize_one_hand(sequence)
    else:
        # Для другого числа признаков возвращаем оригинал
        return sequence


def pad_or_truncate(sequence: np.ndarray, target_length: int = None) -> np.ndarray:
    """
    Приводит последовательность к фиксированной длине.

    Нейросеть (LSTM/GRU) требует, чтобы ВСЕ входные последовательности
    имели одинаковое количество кадров. Мы используем target_length = 30.

    Два случая:
        1. Кадров БОЛЬШЕ, чем нужно (жест записан долго):
           → Берём 30 равномерно распределённых кадров (np.linspace).
             Это как «ускоренная перемотка» — сохраняем движение, но компактнее.

        2. Кадров МЕНЬШЕ, чем нужно (жест записан быстро):
           → Дополняем нулями в конце (zero-padding).
             Keras слой Masking научит нейросеть игнорировать эти нули.

    Аргументы:
        sequence (np.ndarray): Массив формы (N, 63).
        target_length (int): Желаемое количество кадров (по умолчанию из config).

    Возвращает:
        np.ndarray: Массив формы (target_length, 63).
    """
    if target_length is None:
        target_length = config.SEQUENCE_LENGTH  # По умолчанию 30

    num_features = sequence.shape[1] if (sequence.ndim > 1 and sequence.shape[1] > 0) else config.TOTAL_FEATURES
    current_length = sequence.shape[0]

    if current_length == 0:
        return np.zeros((target_length, num_features))

    if current_length > target_length:
        indices = np.linspace(0, current_length - 1, target_length, dtype=int)
        result = sequence[indices]
    elif current_length < target_length:
        padding = np.zeros((target_length - current_length, num_features))
        result = np.vstack([sequence, padding])
    else:
        result = sequence.copy()

    return result


def process_dataset(data_dict: dict) -> tuple:
    """
    Полный конвейер обработки датасета для обучения нейросети.

    Принимает словарь, где:
        - Ключ (label) = название жеста (например, «привет», «спасибо»)
        - Значение = список последовательностей координат
          (несколько видео одного и того же жеста)

    Для КАЖДОЙ последовательности:
        1. normalize_sequence() — центрируем и масштабируем
        2. pad_or_truncate() — приводим к длине 30

    На выходе — три объекта, готовые для подачи в model.fit():
        X — входные данные, форма (N_samples, 30, 162)
        y — метки классов, форма (N_samples,)
        label_map — словарь {название_жеста: числовой_код}

    Аргументы:
        data_dict (dict): Словарь {label: [list_of_sequences]}.
            Каждый элемент list_of_sequences — numpy array формы (N, 63).

    Возвращает:
        tuple: (X, y, label_map)
            X — np.ndarray формы (total_samples, SEQUENCE_LENGTH, 63)
            y — np.ndarray формы (total_samples,) с числовыми метками
            label_map — dict {str: int}, соответствие «жест» → число
    """
    all_sequences = []   # Сюда сложим обработанные последовательности
    all_labels = []       # Сюда — числовые метки классов

    # Создаём маппинг «название жеста» → «число»
    # Пример: {"привет": 0, "спасибо": 1, "пожалуйста": 2}
    # Нейросеть работает с числами, а не с текстом,
    # поэтому каждому жесту присваиваем уникальный номер.
    sorted_labels = sorted(data_dict.keys())
    label_map = {label: idx for idx, label in enumerate(sorted_labels)}

    print(f"\n{'=' * 50}")
    print(f"Обработка датасета")
    print(f"Количество классов (жестов): {len(label_map)}")
    print(f"Маппинг меток: {label_map}")
    print(f"{'=' * 50}\n")

    total_processed = 0
    total_skipped = 0

    for label in sorted_labels:
        sequences = data_dict[label]
        label_idx = label_map[label]

        print(f"Класс '{label}' (код {label_idx}): {len(sequences)} видео")

        for i, seq in enumerate(sequences):
            try:
                # Преобразуем в numpy, если это ещё не numpy
                if not isinstance(seq, np.ndarray):
                    seq = np.array(seq, dtype=np.float64)

                # Проверяем, что данные имеют правильное количество столбцов
                expected_features = config.TOTAL_FEATURES
                if seq.ndim != 2 or seq.shape[1] != expected_features:
                    print(f"  [{i + 1}] ПРОПУСК — неверная форма: {seq.shape}, "
                          f"ожидалось (N, {expected_features})")
                    total_skipped += 1
                    continue

                # Шаг 1: Нормализация (центрирование + масштабирование)
                normalized = normalize_sequence(seq)

                # Шаг 2: Приведение к фиксированной длине
                padded = pad_or_truncate(normalized)

                all_sequences.append(padded)
                all_labels.append(label_idx)
                total_processed += 1

            except Exception as e:
                print(f"  [{i + 1}] ОШИБКА: {type(e).__name__}: {e}")
                total_skipped += 1

        print()

    if total_processed == 0:
        print("[ОШИБКА] Не удалось обработать ни одной последовательности!")
        empty_X = np.zeros((0, config.SEQUENCE_LENGTH,
                            config.NUM_LANDMARKS * config.COORDS_PER_LANDMARK))
        empty_y = np.zeros((0,), dtype=int)
        return empty_X, empty_y, label_map

    # Собираем всё в единые массивы
    X = np.array(all_sequences, dtype=np.float64)
    y = np.array(all_labels, dtype=int)

    print(f"{'=' * 50}")
    print(f"Результат обработки датасета:")
    print(f"  Обработано: {total_processed} последовательностей")
    print(f"  Пропущено:  {total_skipped} последовательностей")
    print(f"  X.shape = {X.shape}  (сэмплы, кадры, координаты)")
    print(f"  y.shape = {y.shape}  (метки)")
    print(f"  Классов:  {len(label_map)}")
    print(f"{'=' * 50}\n")

    return X, y, label_map


def augment_sequence(sequence: np.ndarray,
                     rotation_range: float = 10.0,
                     scale_range: tuple = (0.9, 1.1),
                     noise_level: float = 0.005,
                     time_warp: bool = True) -> np.ndarray:
    """
    Выполняет аугментацию последовательности 3D-координат жеста.

    Методы аугментации:
        1. 3D Поворот (Rotation): случайный поворот вокруг оси Z на угол ±10°.
           Имитирует смену угла съёмки или естественный наклон руки.
        2. Масштабирование (Scale): умножение координат на случайный коэффициент (0.9..1.1).
           Имитирует разную длину рук/пальцев у разных людей.
        3. Гауссов шум (Jittering): добавление небольшого шума N(0, 0.005).
           Имитирует физические дрожания и погрешности камеры.
        4. Временное деформирование (Time Warping): субдискретизация кадров во времени.
           Имитирует ускоренное или замедленное выполнение жеста.

    Аргументы:
        sequence (np.ndarray): Входной массив (30, 162), (30, 126) или (30, 63).
        rotation_range (float): Максимальный угол поворота в градусах.
        scale_range (tuple): Диапазон масштабирования (min, max).
        noise_level (float): Стандартное отклонение гауссова шума.
        time_warp (bool): Включать ли временную деформацию.

    Возвращает:
        np.ndarray: Синтетически изменённый массив той же формы.
    """
    aug_seq = sequence.copy().astype(np.float64)
    num_frames, num_features = aug_seq.shape

    # 1. 3D Поворот вокруг оси Z
    angle_deg = np.random.uniform(-rotation_range, rotation_range)
    angle_rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)

    for frame_idx in range(num_frames):
        frame = aug_seq[frame_idx]
        if np.all(frame == 0.0):
            continue

        for i in range(0, num_features, 3):
            x, y = frame[i], frame[i + 1]
            frame[i] = x * cos_a - y * sin_a
            frame[i + 1] = x * sin_a + y * cos_a

    # 2. Масштабирование (Scale)
    scale_factor = np.random.uniform(scale_range[0], scale_range[1])
    aug_seq *= scale_factor

    # 3. Гауссов шум (Jittering)
    noise = np.random.normal(0, noise_level, size=aug_seq.shape)
    non_zero_mask = (aug_seq != 0.0)
    aug_seq[non_zero_mask] += noise[non_zero_mask]

    # 4. Временное деформирование (Time Warping)
    if time_warp and num_frames > 5:
        warp_factor = np.random.uniform(0.8, 1.2)
        indices = np.linspace(0, num_frames - 1, int(num_frames * warp_factor))
        indices = np.clip(indices, 0, num_frames - 1).astype(int)
        warped_seq = aug_seq[indices]

        aug_seq = pad_or_truncate(warped_seq, target_length=num_frames)

    return aug_seq


def generate_augmented_dataset(X: np.ndarray, y: np.ndarray, factor: int = 3) -> tuple:
    """
    Увеличивает обучающий датасет за счет синтетической аугментации.

    Аргументы:
        X (np.ndarray): Исходные данные формы (N, 30, 162)
        y (np.ndarray): Исходные метки формы (N,)
        factor (int): Коэффициент умножения датасета (например, 3x или 5x)

    Возвращает:
        tuple: (X_augmented, y_augmented) — расширенный датасет
    """
    if factor <= 1 or X.shape[0] == 0:
        return X, y

    X_aug_list = [X]
    y_aug_list = [y]

    num_samples = X.shape[0]
    num_copies = factor - 1

    print(f"  Генерация аугментированных данных ({factor}x): {num_samples} -> {num_samples * factor} примеров...")

    for _ in range(num_copies):
        synthetic_samples = []
        for i in range(num_samples):
            aug_sample = augment_sequence(X[i])
            synthetic_samples.append(aug_sample)

        X_aug_list.append(np.array(synthetic_samples, dtype=np.float64))
        y_aug_list.append(y.copy())

    X_final = np.concatenate(X_aug_list, axis=0)
    y_final = np.concatenate(y_aug_list, axis=0)

    shuffle_idx = np.random.permutation(X_final.shape[0])
    return X_final[shuffle_idx], y_final[shuffle_idx]


# ============================================================
# Точка входа — пример и тест нормализации
# ============================================================
if __name__ == "__main__":
    """
    Демонстрация работы нормализации на синтетических данных.
    Запуск: python src/normalize.py
    """
    print("=== Демонстрация нормализации ===\n")

    # Создаём синтетические данные: 10 кадров × 63 координаты
    # (как если бы мы извлекли 10 кадров из видео)
    np.random.seed(42)
    fake_sequence = np.random.rand(10, 63)

    print(f"Исходные данные: {fake_sequence.shape}")
    print(f"  Первый кадр (первые 9 чисел = 3 точки):")
    print(f"    {fake_sequence[0, :9].round(3)}")

    # Шаг 1: Нормализация
    normalized = normalize_sequence(fake_sequence)
    print(f"\nПосле нормализации: {normalized.shape}")
    print(f"  Запястье (должно быть ~0,0,0):")
    print(f"    {normalized[0, :3].round(6)}")
    print(f"  Диапазон значений: [{normalized.min():.4f}, {normalized.max():.4f}]")

    # Шаг 2: Приведение к длине 30
    padded = pad_or_truncate(normalized)
    print(f"\nПосле pad_or_truncate: {padded.shape}")
    print(f"  Последний реальный кадр (кадр 10, сумма != 0):")
    print(f"    sum = {padded[9].sum():.4f}")
    print(f"  Первый padding-кадр (кадр 11, сумма = 0):")
    print(f"    sum = {padded[10].sum():.4f}")

    # Шаг 3: Тест process_dataset
    print(f"\n{'=' * 50}")
    print("Тест process_dataset с синтетическими данными:")
    print(f"{'=' * 50}")

    fake_dataset = {
        "privet": [np.random.rand(15, 63), np.random.rand(40, 63)],
        "spasibo": [np.random.rand(25, 63), np.random.rand(10, 63)],
    }

    X, y, label_map = process_dataset(fake_dataset)

    print(f"Финальные данные:")
    print(f"  X.shape = {X.shape}")
    print(f"  y = {y}")
    print(f"  label_map = {label_map}")
    print(f"\n=== Демонстрация завершена ===")
