"""
predict.py — Распознавание жестов КЖЯ в реальном времени через веб-камеру или из видеофайла

КАК ЭТО РАБОТАЕТ (для защиты перед жюри):
===========================================

1. ПОЧЕМУ НУЖНО НАКАПЛИВАТЬ РОВНО 30 КАДРОВ?
   BiLSTM обрабатывает 30 кадров жеста с полным вектором из двух рук и точек лица (30, 162).
   Один отдельный кадр — это лишь «стоп-кадр», по которому нельзя точно определить
   динамический жест (например, машет ли рука «привет» или показывает другой жест).
   Мы накапливаем непрерывный поток из 30 кадров движения.

2. КАК РАБОТАЕТ БУФЕР КАДРОВ (FIFO — First In, First Out):
   Буфер — это скользящее окно фиксированного размера (30 кадров).
   Когда приходит новый кадр, он добавляется в КОНЕЦ буфера, а самый СТАРЫЙ кадр
   ИЗВЛЕКАЕТСЯ из начала. Это позволяет непрерывно анализировать жест в реальном времени,
   обновляя предсказание на каждом новом кадре.

3. ПОЧЕМУ ДОБАВЛЯЕМ РАЗМЕРНОСТЬ БАТЧА (1, 30, 162)?
   Keras-модели всегда обрабатывают данные батчами (наборами примеров).
   Даже если мы подаём один-единственный жест, модель ожидает 3D-тензор:
   (количество_примеров, кадры, координаты) = (1, 30, 162).
   Операция np.expand_dims(sequence, axis=0) добавляет единичную ось слева.

4. ЧТО ТАКОЕ CONFIDENCE И ПОРОГ УВЕРЕННОСТИ (Threshold):
   Softmax на выходе нейросети возвращает вероятности для каждого класса (например, [0.85, 0.10, 0.05]).
   Confidence — это максимальная вероятность (0.85 = 85%).
   Если confidence < 0.6 (60%), модель считает, что жест «неразборчив» или рука находится
   в промежуточном движении. Порог предотвращает ложные срабатывания.
"""

import os
import sys
import time
from collections import deque

# Добавляем корневую папку проекта в путь импорта
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

import config
from src.normalize import normalize_sequence, pad_or_truncate
from src.extract_landmarks import (
    MODEL_PATH, download_model_if_missing, create_face_landmark_pipeline,
    extract_face_features, canonical_hand_label,
)
from src.training_utils import load_label_map

try:
    import tensorflow as tf
except ImportError:
    tf = None


def load_model_and_labels(model_path: str = None, map_path: str = None) -> tuple:
    """
    Загружает обученную модель Keras (.h5) и словарь меток (.json).

    Аргументы:
        model_path (str): Путь к файлу модели .h5 (по умолчанию из config.MODELS_DIR)
        map_path (str): Путь к файлу маппинга меток .json (по умолчанию из config.MODELS_DIR)

    Возвращает:
        tuple: (model, label_map)
            model — загруженный объект tf.keras.Model
            label_map — словарь {числовой_индекс: "название_жеста"}
    """
    if model_path is None:
        model_path = os.path.join(config.MODELS_DIR, "sign_model.h5")
    if map_path is None:
        map_path = os.path.join(config.MODELS_DIR, "label_map.json")

    # Проверка наличия файлов
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"[ОШИБКА] Файл модели не найден: {model_path}")
    if not os.path.exists(map_path):
        raise FileNotFoundError(f"[ОШИБКА] Файл меток не найден: {map_path}")

    # Загружаем модель
    print(f"Загрузка модели из {model_path}...")
    model = tf.keras.models.load_model(model_path)

    # Загружаем и проверяем соответствие карты меток версии признаков.
    print(f"Загрузка меток из {map_path}...")
    label_map = load_label_map(map_path)

    print(f"[OK] Модель и {len(label_map)} меток успешно загружены.")
    return model, label_map


class PredictionSmoother:
    """
    Класс экспоненциального сглаживания (EMA) вероятностей предсказания.

    Формула:
        S_t = alpha * P_t + (1 - alpha) * S_{t-1}

    Зачем нужно сглаживание:
        Без сглаживания текст на экране веб-камеры может «мерцать» при смене кадров.
        Экспоненциальное сглаживание плавно фильтрует вероятности, делая отображение
        стабильным и профессиональным.

    Аргументы:
        alpha (float): Коэффициент сглаживания от 0.1 до 1.0 (по умолчанию 0.35).
    """
    def __init__(self, alpha: float = 0.35):
        self.alpha = alpha
        self.smoothed_probs = None

    def update(self, raw_probs: np.ndarray) -> np.ndarray:
        raw_probs = np.array(raw_probs, dtype=np.float64)
        if self.smoothed_probs is None or len(self.smoothed_probs) != len(raw_probs):
            self.smoothed_probs = raw_probs.copy()
        else:
            self.smoothed_probs = self.alpha * raw_probs + (1.0 - self.alpha) * self.smoothed_probs
        return self.smoothed_probs

    def reset(self):
        self.smoothed_probs = None


def extract_live_frame_features(
    detection_result, frame_rgb, face_region_detector, face_landmarker,
    *, input_mirrored: bool = False,
):
    """Keep face motion in the camera sequence even when a hand briefly drops."""
    left_coords = [0.0] * 63
    right_coords = [0.0] * 63
    hand_found = bool(detection_result.hand_landmarks)
    if hand_found:
        for hand_lms, handedness in zip(detection_result.hand_landmarks, detection_result.handedness):
            coords = []
            for landmark in hand_lms:
                coords.extend([landmark.x, landmark.y, landmark.z])
            label = canonical_hand_label(
                handedness[0].category_name, input_mirrored=input_mirrored
            )
            if label == "Left":
                left_coords = coords
            else:
                right_coords = coords
    face_coords = extract_face_features(frame_rgb, face_region_detector, face_landmarker)
    return left_coords + right_coords + face_coords, hand_found


def predict_from_sequence(sequence: np.ndarray,
                          model: tf.keras.Model,
                          label_map: dict,
                          smoother: PredictionSmoother = None) -> tuple:
    """
    Выполняет предсказание жеста по массиву координат.

    Возвращает:
        tuple: (predicted_word, confidence, probabilities)
    """
    if sequence is None or len(sequence) == 0:
        return "Неизвестно", 0.0, np.array([0.0])

    norm_seq = normalize_sequence(sequence)
    padded_seq = pad_or_truncate(norm_seq, target_length=config.SEQUENCE_LENGTH)
    batch_input = np.expand_dims(padded_seq, axis=0)

    predictions = model.predict(batch_input, verbose=0)[0]  # Вектор вероятностей

    if smoother is not None:
        predictions = smoother.update(predictions)

    predicted_idx = int(np.argmax(predictions))
    confidence = float(np.max(predictions))
    predicted_word = label_map.get(predicted_idx, f"Класс_{predicted_idx}")

    return predicted_word, confidence, predictions


def model_has_distinguishable_classes(label_map: dict) -> bool:
    """A classifier with fewer than two distinct labels cannot recognize signs."""
    labels = {str(label).strip().casefold() for label in label_map.values() if str(label).strip()}
    return len(labels) >= 2


def draw_hand_landmarks(frame: np.ndarray, landmarks_flat: list) -> None:
    """
    Визуализирует ключевые точки рук и мимики лица на кадре с помощью OpenCV.
    """
    h, w, _ = frame.shape

    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)
    ]

    colors = [(0, 212, 170), (255, 152, 0)]  # Левая (бирюзовая), Правая (оранжевая)

    # 1. Отрисовка рук (0..125)
    for hand_idx, offset in enumerate(range(0, min(126, len(landmarks_flat)), 63)):
        sub_lms = landmarks_flat[offset:offset + 63]
        if len(sub_lms) < 63 or all(v == 0.0 for v in sub_lms):
            continue

        color = colors[hand_idx % len(colors)]
        coords_2d = []

        for i in range(0, 63, 3):
            x = int(sub_lms[i] * w)
            y = int(sub_lms[i + 1] * h)
            coords_2d.append((x, y))
            cv2.circle(frame, (x, y), 5, color, -1)

        for p1, p2 in connections:
            if p1 < len(coords_2d) and p2 < len(coords_2d):
                cv2.line(frame, coords_2d[p1], coords_2d[p2], (255, 255, 255), 2)

    # 2. Отрисовка лица (126..161)
    if len(landmarks_flat) >= 162:
        face_lms = landmarks_flat[126:162]
        if not all(v == 0.0 for v in face_lms):
            for i in range(0, 36, 3):
                fx = int(face_lms[i] * w)
                fy = int(face_lms[i + 1] * h)
                cv2.circle(frame, (fx, fy), 3, (255, 255, 0), -1)  # Желтые точки лица


def real_time_predict(model_path: str = None,
                      map_path: str = None,
                      confidence_threshold: float = 0.6) -> None:
    """
    Запускает распознавание жестов в реальном времени с веб-камеры (Руки + Мимика лица).
    """
    default_model = os.path.join(config.MODELS_DIR, "sign_model.h5")
    default_map = os.path.join(config.MODELS_DIR, "label_map.json")
    active_model_path, active_map_path = model_path or default_model, map_path or default_map
    matcher = None
    model, label_map = None, {}
    if os.path.isfile(active_model_path) and os.path.isfile(active_map_path) and tf is not None:
        try:
            model, label_map = load_model_and_labels(active_model_path, active_map_path)
            if not model_has_distinguishable_classes(label_map):
                print("Модель содержит менее двух разных меток; это не распознавание. Переключаюсь на motion-примеры.")
                model, label_map = None, {}
        except Exception as error:
            print(f"Модель не загружена ({error}); переключаюсь на motion-примеры.")
    elif os.path.isfile(active_model_path) and tf is None:
        print("TensorFlow недоступен; переключаюсь на motion-примеры.")

    if model is None:
        from src.motion_matcher import MotionLibraryMatcher
        matcher = MotionLibraryMatcher()
        if not matcher.references:
            print("[ОШИБКА] Нет обученной модели и motion-клипов для сравнения.")
            return
        print("Режим камеры: ближайший пример motion-библиотеки; это НЕ обученный классификатор.")
    download_model_if_missing()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ОШИБКА] Не удалось открыть веб-камеру.")
        return

    print("\n" + "=" * 60)
    print("ЗАПУСК РАСПОЗНАВАНИЯ В РЕАЛЬНОМ ВРЕМЕНИ (РУКИ + МИМИКА ЛИЦА)")
    print("  Нажмите 'q' в окне видео для выхода.")
    print("=" * 60 + "\n")

    buffer = deque(maxlen=config.SEQUENCE_LENGTH)

    hand_options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=config.NUM_HANDS,
        min_hand_detection_confidence=config.MIN_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=config.MIN_TRACKING_CONFIDENCE
    )

    face_region_detector, face_landmarker = create_face_landmark_pipeline()

    current_gesture = "Ожидание руки..."
    current_confidence = 0.0
    current_distance = None

    fps_start_time = time.time()
    fps_frame_count = 0
    fps = 0.0
    match_frame_count = 0

    smoother = PredictionSmoother(alpha=0.35)

    with vision.HandLandmarker.create_from_options(hand_options) as detector:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                print("[ОШИБКА] Не удалось получить кадр с камеры.")
                break
            match_frame_count += 1

            h, w, _ = frame.shape

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

            detection_result = detector.detect(mp_image)

            frame_coords, hand_found = extract_live_frame_features(
                detection_result, frame_rgb, face_region_detector, face_landmarker
            )
            if hand_found:
                draw_hand_landmarks(frame, frame_coords)
            else:
                # Do not leave the last recognized/matched label on screen when
                # the signer has moved out of frame. Zeros still enter the
                # temporal buffer so the sequence keeps its real timing.
                current_gesture = "Покажите жест перед камерой..."
                current_confidence = 0.0
                current_distance = None
                if smoother is not None:
                    smoother.reset()

            # Не выбрасываем кадры без рук: иначе нарушаются длительность
            # жеста и скорость движения в скользящем временном окне.
            buffer.append(frame_coords)

            # Если набралось 30 кадров в буфере — выполняем предсказание со сглаживанием
            if len(buffer) == config.SEQUENCE_LENGTH and hand_found:
                seq_array = np.array(list(buffer))
                if matcher is not None:
                    if not matcher.can_classify:
                        current_gesture = (
                            f"Недостаточно классов ({matcher.class_count}); "
                            "добавьте видео других жестов"
                        )
                        current_distance = None
                    elif match_frame_count % 6 == 0:
                        match = matcher.match(seq_array)
                        if match:
                            current_gesture = f"Ближайший шаблон: {match['lemma']}"
                            current_distance = match["distance"]
                        else:
                            current_gesture = "Нужно непрерывное движение руки..."
                            current_distance = None
                else:
                    gesture, conf, _ = predict_from_sequence(seq_array, model, label_map, smoother=smoother)
                    if conf >= confidence_threshold:
                        current_gesture = gesture
                        current_confidence = conf
                    else:
                        current_gesture = "Неуверенность..."
                        current_confidence = conf

            # Подсчёт FPS (кадров в секунду)
            fps_frame_count += 1
            if time.time() - fps_start_time >= 1.0:
                fps = fps_frame_count / (time.time() - fps_start_time)
                fps_frame_count = 0
                fps_start_time = time.time()

            # --- ОТОБРАЖЕНИЕ ИНФОРМАЦИИ НА КАДРЕ (Overlay) ---
            # Переворот нужен только для привычного selfie-preview. Детекция
            # выполняется до зеркалирования, как и при импорте видео в базу,
            # чтобы left/right и координаты совпадали с обучающими примерами.
            frame = cv2.flip(frame, 1)
            # Верхний плашка-фон
            cv2.rectangle(frame, (0, 0), (w, 80), (15, 15, 46), -1)
            cv2.line(frame, (0, 80), (w, 80), (0, 212, 170), 2)

            # Текст предсказанного жеста
            status_color = (0, 212, 170) if model is not None and current_confidence >= confidence_threshold else (0, 165, 255)
            cv2.putText(frame, current_gesture, (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.78, status_color, 2, cv2.LINE_AA)

            # Текст уверенности и состояния буфера
            detail = (f"Расстояние до примера: {current_distance:.3f}" if current_distance is not None
                      else f"Уверенность: {current_confidence * 100:.1f}%" if model is not None
                      else "Нет совпадения в motion-библиотеке")
            cv2.putText(frame, f"{detail}  |  Буфер: {len(buffer)}/30  |  FPS: {fps:.1f}",
                        (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

            # Показываем окно
            cv2.imshow("KZH Sign Language Translator — Real-Time Predict", frame)

            # Выход по клавише 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("Завершение работы по нажатию клавиши 'q'...")
                break

    # Грациозное освобождение ресурсов
    cap.release()
    cv2.destroyAllWindows()
    if face_region_detector is not None:
        face_region_detector.close()
    if face_landmarker is not None:
        face_landmarker.close()
    print("[OK] Камера освобождена, окна закрыты.")


def predict_from_video(video_path: str,
                       model_path: str = None,
                       map_path: str = None,
                       confidence_threshold: float = 0.6) -> None:
    """
    Выполняет распознавание жестов из готового видеофайла.

    Аргументы:
        video_path (str): Путь к файлу видео (.mp4, .avi и т.д.)
        model_path (str): Путь к модели .h5
        map_path (str): Путь к маппингу .json
        confidence_threshold (float): Порог уверенности
    """
    if not os.path.exists(video_path):
        print(f"[ОШИБКА] Видеофайл не найден: {video_path}")
        return

    model, label_map = load_model_and_labels(model_path, map_path)
    download_model_if_missing()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ОШИБКА] Не удалось открыть видео: {video_path}")
        return

    print(f"\nАнализ видеофайла: {os.path.basename(video_path)}")

    buffer = deque(maxlen=config.SEQUENCE_LENGTH)

    base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        num_hands=config.NUM_HANDS,
        min_hand_detection_confidence=config.MIN_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=config.MIN_TRACKING_CONFIDENCE
    )
    face_region_detector, face_landmarker = create_face_landmark_pipeline()

    current_gesture = "Анализ..."
    current_confidence = 0.0

    smoother = PredictionSmoother(alpha=0.35)

    with vision.HandLandmarker.create_from_options(options) as detector:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            h, w, _ = frame.shape
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

            detection_result = detector.detect(mp_image)

            frame_coords, hand_found = extract_live_frame_features(
                detection_result, frame_rgb, face_region_detector, face_landmarker
            )
            buffer.append(frame_coords)
            if hand_found:
                draw_hand_landmarks(frame, frame_coords)

            if len(buffer) == config.SEQUENCE_LENGTH and hand_found:
                seq_array = np.array(list(buffer))
                gesture, conf, _ = predict_from_sequence(seq_array, model, label_map, smoother=smoother)

                if conf >= confidence_threshold:
                    current_gesture = gesture
                    current_confidence = conf

            # Рисуем статус
            cv2.rectangle(frame, (0, 0), (w, 60), (15, 15, 46), -1)
            cv2.putText(frame, f"Жест: {current_gesture} ({current_confidence * 100:.1f}%)",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 212, 170), 2, cv2.LINE_AA)

            cv2.imshow("Video Prediction Test", frame)
            if cv2.waitKey(25) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()
    if face_region_detector is not None:
        face_region_detector.close()
    if face_landmarker is not None:
        face_landmarker.close()
    print("[OK] Тест видео завершен.")


# ============================================================
# Точка входа — при прямом запуске
# ============================================================
if __name__ == "__main__":
    """
    Пример запуска:
        python src/predict.py
    Или для видео:
        python src/predict.py test_video.mp4
    """
    if len(sys.argv) > 1:
        video_arg = sys.argv[1]
        predict_from_video(video_arg)
    else:
        real_time_predict()
