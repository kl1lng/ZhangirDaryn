"""
extract_landmarks.py — Извлечение 3D-координат рук и мимики лица из видео с помощью MediaPipe Tasks API

КАК ЭТО РАБОТАЕТ (для защиты перед жюри):
===========================================

1. ДЕТЕКЦИЯ ДВУХ РУК (126 координат):
   - Левая рука: 21 точка × 3 (x,y,z) = 63 числа
   - Правая рука: 21 точка × 3 (x,y,z) = 63 числа

2. ДЕТЕКЦИЯ МИМИКИ ЛИЦА (36 координат):
   В жестовом языке эмоции и движение губ/бровей передают важный контекст (вопросы, отрицания).
   Мы отслеживаем 12 ключевых точек лица:
   - Губы (верхняя, нижняя, левый и правый уголки) -> 4 точки
   - Левая и правая брови -> 6 точек
   - Переносица и кончик носа -> 2 точки (опорный центр)
   12 точек × 3 координаты = 36 чисел

ИТОГО НА КАЖДЫЙ КАДР: 126 (руки) + 36 (лицо) = 162 координаты!
"""

import os
import sys
import glob
import urllib.request
import zipfile

# Добавляем корневую папку проекта в путь импорта
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import config

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hand_landmarker.task")

FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
FACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "face_landmarker.task")

# 12 ключевых точек лица (губы, брови, нос)
FACE_INDICES = [1, 6, 13, 14, 61, 291, 70, 107, 105, 300, 336, 334]
FACE_EXTRACTOR_VERSION = "face-crop-fallback-v2"
HAND_EXTRACTOR_VERSION = "hand-handedness-unmirrored-v1"
POSE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pose_landmarker_lite.task")
POSE_EXTRACTOR_VERSION = "mediapipe-pose-video-upper-body-v4-world"
POSE_INDICES = (11, 12, 13, 14, 15, 16)  # плечи, локти, запястья


def extract_body_pose_from_video(
    video_path: str, *, expected_frames: int | None = None,
    start_frame: int = 0, end_frame: int | None = None,
    include_world: bool = False,
):
    """Return frame-aligned upper-body landmarks, or None when no local model exists.

    The model is intentionally user-provided: importing a video never silently
    downloads an additional model. Values are normalized image x/y/z; an
    invisible joint is represented by three zeros for that frame.
    """
    if not os.path.isfile(POSE_MODEL_PATH):
        return None
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise ValueError(f"Не удалось открыть видео для body-pose: {video_path}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not np.isfinite(source_fps) or source_fps <= 0:
        source_fps = 30.0
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = int(start_frame)
    end_frame = total_frames if end_frame is None else int(end_frame)
    if start_frame < 0 or end_frame <= start_frame or end_frame > total_frames:
        capture.release()
        raise ValueError(
            f"Некорректный pose-диапазон [{start_frame}, {end_frame}) "
            f"для видео из {total_frames} кадров"
        )
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=POSE_MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.35,
        min_pose_presence_confidence=0.35,
        min_tracking_confidence=0.35,
        output_segmentation_masks=False,
    )
    frames = []
    world_frames = []
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        frame_index = start_frame
        while frame_index < end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            result = landmarker.detect_for_video(image, int(frame_index * 1000.0 / source_fps))
            landmarks = result.pose_landmarks[0] if result.pose_landmarks else None
            world_landmarks = result.pose_world_landmarks[0] if result.pose_world_landmarks else None
            row = []
            world_row = []
            for index in POSE_INDICES:
                point = landmarks[index] if landmarks else None
                visible = point is not None and getattr(point, "visibility", 1.0) >= 0.35
                row.extend((float(point.x), float(point.y), float(point.z)) if visible else (0., 0., 0.))
                world_point = world_landmarks[index] if visible and world_landmarks else None
                world_row.extend((float(world_point.x), float(world_point.y), float(world_point.z)) if world_point else (0., 0., 0.))
            frames.append(row)
            world_frames.append(world_row)
            frame_index += 1
    capture.release()
    if expected_frames is not None and len(frames) != expected_frames:
        raise ValueError(f"Pose дорожка: {len(frames)} кадров при {expected_frames} кадрах motion")
    if not frames or not any(any(row) for row in frames):
        return (None, None) if include_world else None
    image_pose = np.asarray(frames, dtype=np.float32)
    if not include_world:
        return image_pose
    world_pose = np.asarray(world_frames, dtype=np.float32)
    return image_pose, world_pose if np.any(world_pose) else None


def canonical_hand_label(category_name: str, *, input_mirrored: bool = False) -> str:
    """Convert MediaPipe's selfie-assumed handedness to anatomical identity."""
    if input_mirrored:
        return category_name
    if category_name == "Left":
        return "Right"
    if category_name == "Right":
        return "Left"
    return category_name


def create_face_landmark_pipeline():
    """Create a face detector + landmarker; detector crops small faces first."""
    if not os.path.isfile(FACE_MODEL_PATH):
        return None, None
    with zipfile.ZipFile(FACE_MODEL_PATH) as archive:
        detector_model = archive.read("face_detector.tflite")
    detector_options = vision.FaceDetectorOptions(
        base_options=python.BaseOptions(model_asset_buffer=detector_model),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.10,
        min_suppression_threshold=0.3,
    )
    landmarker_options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.10,
        min_face_presence_confidence=0.10,
        min_tracking_confidence=0.10,
    )
    return (vision.FaceDetector.create_from_options(detector_options),
            vision.FaceLandmarker.create_from_options(landmarker_options))


def extract_face_features(frame_rgb, region_detector, face_landmarker):
    """Detect a face in the full frame, landmark a padded crop, map to full-frame XY."""
    if region_detector is None or face_landmarker is None:
        return [0.0] * config.FACE_FEATURES
    height, width = frame_rgb.shape[:2]
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    # Preserve the model's native full-frame inference first. Crop inference is
    # a fallback for small faces and must never reduce existing coverage.
    result = face_landmarker.detect(image)
    if result.face_landmarks:
        features = _select_face_features(result.face_landmarks[0])
        if features:
            return features
    detections = region_detector.detect(image).detections or []
    detections = sorted(detections,
                        key=lambda d: max((c.score for c in d.categories), default=0),
                        reverse=True)
    for detection in detections:
        box = detection.bounding_box
        # Face detector boxes are often square and tight; a wider context helps
        # the landmarker's own detector when the source image is low resolution.
        pad_x, pad_y = int(box.width * 0.45), int(box.height * 0.45)
        x0, y0 = max(0, box.origin_x - pad_x), max(0, box.origin_y - pad_y)
        x1 = min(width, box.origin_x + box.width + pad_x)
        y1 = min(height, box.origin_y + box.height + pad_y)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = frame_rgb[y0:y1, x0:x1]
        original_crop_h, original_crop_w = crop.shape[:2]
        side = max(original_crop_h, original_crop_w)
        pad_top = (side - original_crop_h) // 2
        pad_left = (side - original_crop_w) // 2
        # Keep the ROI square-ish by padding its shorter dimension. This avoids
        # a stretched face when a detection near an image edge clips one axis.
        crop = cv2.copyMakeBorder(
            crop,
            top=pad_top,
            bottom=side - original_crop_h - pad_top,
            left=pad_left,
            right=side - original_crop_w - pad_left,
            borderType=cv2.BORDER_REPLICATE,
        )
        result = face_landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
        if not result.face_landmarks:
            continue
        crop_h, crop_w = crop.shape[:2]
        face = result.face_landmarks[0]
        values = _select_face_features(
            face,
            transform=lambda point: ((x0 + point.x * crop_w - pad_left) / width,
                                     (y0 + point.y * crop_h - pad_top) / height,
                                     point.z * crop_w / width),
        )
        if len(values) == config.FACE_FEATURES:
            return values
    return [0.0] * config.FACE_FEATURES


def _select_face_features(landmarks, transform=None):
    values = []
    for index in FACE_INDICES:
        if index >= len(landmarks):
            return []
        point = landmarks[index]
        values.extend(transform(point) if transform else (point.x, point.y, point.z))
    return values if len(values) == config.FACE_FEATURES else []


def download_model_if_missing():
    """Скачивает файлы моделей MediaPipe с серверов Google, если их нет."""
    if not os.path.exists(MODEL_PATH):
        print(f"Загрузка модели MediaPipe Hand Landmarker ({MODEL_URL})...")
        try:
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            print(f"[OK] Модель рук сохранена в {MODEL_PATH}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось скачать модель рук: {e}")

    if not os.path.exists(FACE_MODEL_PATH):
        print(f"Загрузка модели MediaPipe Face Landmarker ({FACE_MODEL_URL})...")
        try:
            urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL_PATH)
            print(f"[OK] Модель лица сохранена в {FACE_MODEL_PATH}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось скачать модель лица: {e}")


def extract_from_video(
    video_path: str, *, input_mirrored: bool = False,
    start_frame: int = 0, end_frame: int | None = None,
) -> list:
    """
    Извлекает 3D-координаты рук и лица из видеофайла.

    Аргументы:
        video_path (str): Путь к видеофайлу.

    Возвращает:
        list of lists: Каждый внутренний список — 162 числа (126 рук + 36 лица).
    """
    download_model_if_missing()

    if not os.path.isfile(video_path):
        print(f"[ОШИБКА] Файл не найден: {video_path}")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ОШИБКА] Не удалось открыть видео: {video_path}")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = int(start_frame)
    end_frame = total_frames if end_frame is None else int(end_frame)
    if start_frame < 0 or end_frame <= start_frame or end_frame > total_frames:
        cap.release()
        raise ValueError(
            f"Некорректный диапазон кадров [{start_frame}, {end_frame}) "
            f"для видео из {total_frames} кадров"
        )
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"  Видео: {os.path.basename(video_path)}")
    print(f"  Всего кадров: {total_frames}, FPS: {fps:.1f}")

    all_landmarks = []

    # Детектор рук
    hand_options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=config.NUM_HANDS,
        min_hand_detection_confidence=config.MIN_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=config.MIN_TRACKING_CONFIDENCE
    )

    # Детектор лица
    face_region_detector, face_landmarker = create_face_landmark_pipeline()

    with vision.HandLandmarker.create_from_options(hand_options) as hand_detector:
        frame_index = start_frame
        detected_count = 0

        while frame_index < end_frame:
            success, frame = cap.read()
            if not success:
                break

            frame_index += 1
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

            # 1. Извлечение рук. В motion-клип сохраняем и кадры без рук,
            # чтобы не сжимать время и не склеивать разорванные участки движения.
            hand_result = hand_detector.detect(mp_image)
            left_coords = [0.0] * 63
            right_coords = [0.0] * 63

            if hand_result.hand_landmarks:
                for hand_lms, handedness in zip(hand_result.hand_landmarks, hand_result.handedness):
                    hand_type = canonical_hand_label(
                        handedness[0].category_name, input_mirrored=input_mirrored
                    )
                    coords = []
                    for lm in hand_lms:
                        coords.extend([lm.x, lm.y, lm.z])
                    if hand_type == "Left":
                        left_coords = coords
                    else:
                        right_coords = coords

            hand_features = left_coords + right_coords  # 126 чисел

            # 2. Извлечение лица
            face_coords = extract_face_features(frame_rgb, face_region_detector, face_landmarker)

            # Склеиваем координаты: 126 рук + 36 лица = 162 числа
            frame_coords = hand_features + face_coords

            all_landmarks.append(frame_coords)
            if hand_result.hand_landmarks:
                detected_count += 1

    if face_region_detector is not None:
        face_region_detector.close()
    if face_landmarker is not None:
        face_landmarker.close()

    cap.release()

    clip_frames = max(frame_index - start_frame, 0)
    print(f"  Рука/лицо найдены в {detected_count} из {clip_frames} кадров "
          f"({detected_count / max(clip_frames, 1) * 100:.1f}%)")

    return all_landmarks


def extract_from_folder(folder_path: str) -> dict:
    """Обрабатывает все видеофайлы в папке."""
    if not os.path.isdir(folder_path):
        print(f"[ОШИБКА] Папка не найдена: {folder_path}")
        return {}

    video_extensions = ["*.mp4", "*.avi", "*.mov", "*.mkv"]
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(folder_path, ext)))

    if not video_files:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] В папке нет видеофайлов: {folder_path}")
        return {}

    print(f"\n{'=' * 50}")
    print(f"Обработка папки: {folder_path}")
    print(f"Найдено видеофайлов: {len(video_files)}")
    print(f"{'=' * 50}\n")

    results = {}

    for i, video_path in enumerate(sorted(video_files), start=1):
        filename = os.path.basename(video_path)
        print(f"[{i}/{len(video_files)}] Обрабатываю: {filename}")

        try:
            landmarks = extract_from_video(video_path)
            if len(landmarks) > 0:
                results[filename] = landmarks
                print(f"  [OK] Сохранено {len(landmarks)} кадров\n")
            else:
                print(f"  [ПУСТО] Данные не найдены ни в одном кадре\n")
        except Exception as e:
            print(f"  [ОШИБКА] {type(e).__name__}: {e}\n")

    print(f"{'=' * 50}")
    print(f"Итого: обработано {len(results)} из {len(video_files)} видео")
    print(f"{'=' * 50}\n")

    return results


def save_landmarks(landmarks, output_path: str) -> None:
    """Сохраняет landmarks в numpy-файл."""
    try:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        np.save(output_path, np.array(landmarks, dtype=object), allow_pickle=True)
        print(f"[OK] Данные сохранены: {output_path}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить файл: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python src/extract_landmarks.py <видео_или_папка>")
        sys.exit(1)

    input_path = sys.argv[1]

    if os.path.isfile(input_path):
        print(f"\nИзвлечение ключевых точек из видео: {input_path}\n")
        landmarks = extract_from_video(input_path)
        if landmarks:
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(config.DATA_DIR, f"{base_name}_landmarks.npy")
            save_landmarks(landmarks, output_path)
        else:
            print("\nНе удалось извлечь данные из видео.")
    elif os.path.isdir(input_path):
        results = extract_from_folder(input_path)
        if results:
            output_path = os.path.join(config.DATA_DIR, "all_landmarks.npy")
            save_landmarks(results, output_path)
    else:
        print(f"[ОШИБКА] Путь не найден: {input_path}")
