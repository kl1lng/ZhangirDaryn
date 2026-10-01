"""
Конфигурационный файл проекта kzh-sign-translator.
Содержит пути к директориям, параметры MediaPipe и настройки ИИ-модели.
"""

import os
from pathlib import Path

# Базовый путь к проекту
BASE_DIR = Path(__file__).resolve().parent

# --- Пути к директориям ---
# Директория для хранения данных и датасетов
DATA_DIR = os.path.join(BASE_DIR, "data")

# Директория для обученных моделей TensorFlow
MODELS_DIR = os.path.join(BASE_DIR, "models")

# Реестр жестов и motion-клипов для 3D-аватара
MOTION_DB_PATH = os.path.join(DATA_DIR, "motion_library.sqlite3")

# Директория для внешних ресурсов (AI-Ym, KSL-EMO)
EXTERNAL_DIR = os.path.join(BASE_DIR, "external")

# Директории для видео
RAW_VIDEOS_DIR = os.path.join(DATA_DIR, "raw_videos")
EXTERNAL_VIDEOS_DIR = os.path.join(EXTERNAL_DIR, "videos")

# --- Параметры распознавания MediaPipe (Руки + Мимика лица) ---
# Максимальное количество отслеживаемых рук (2 руки = левая + правая)
NUM_HANDS = 2

# Количество ключевых точек на одной руке
NUM_LANDMARKS = 21

# Количество координат для каждой точки (X, Y, Z)
COORDS_PER_LANDMARK = 3

# Количество координат от обеих рук: 21 точка × 3 координаты × 2 руки = 126 чисел
HAND_FEATURES = NUM_LANDMARKS * COORDS_PER_LANDMARK * NUM_HANDS

# Детекция ключевых точек лица (мимика, губы, брови)
USE_FACE_LANDMARKS = True
NUM_FACE_LANDMARKS = 12
FACE_FEATURES = NUM_FACE_LANDMARKS * COORDS_PER_LANDMARK  # 12 × 3 = 36 чисел

# Общее количество признаков на один кадр:
# 126 (руки) + 36 (лицо) = 162 числа
TOTAL_FEATURES = HAND_FEATURES + FACE_FEATURES

# Минимальный порог уверенности для детекции руки/лица (от 0.0 до 1.0)
MIN_DETECTION_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# --- Параметры последовательностей для нейросети ---
# Длина временной последовательности кадров (количество кадров на один жест)
SEQUENCE_LENGTH = 30

# Клип с худшей видимостью рук сохраняется для просмотра/повторной обработки,
# но не используется как надёжный обучающий пример или эталон распознавания.
MOTION_MIN_HAND_COVERAGE = 0.5
