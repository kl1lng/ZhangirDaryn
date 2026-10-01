"""
Скрипт первичной инициализации проекта kzh-sign-translator.
- Создает необходимую структуру директорий.
- Проверяет доступность зависимостей Python.
"""

import sys
import os
import importlib

# Настройка кодировки вывода для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Список необходимых папок для создания
DIRECTORIES = [
    "data",
    "models",
    "external",
    "docs",
    "notebooks",
    "web",
    os.path.join("data", "raw_videos"),
    os.path.join("external", "videos"),
]

# Список библиотек для проверки (имена модулей для import)
REQUIRED_PACKAGES = [
    "streamlit",
    "cv2",
    "mediapipe",
    "numpy",
    "PIL",
    "plotly",
]


def create_directories():
    """Создает необходимые директории проекта."""
    print("[1/2] Создание директорий проекта...")
    for directory in DIRECTORIES:
        os.makedirs(directory, exist_ok=True)
        print(f"  [OK] Директория готова: {directory}")


def check_dependencies():
    """Проверяет установку требуемых Python-пакетов."""
    print("\n[2/2] Проверка установленных зависимостей...")
    all_installed = True
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
            print(f"  [OK] {package} — установлен")
        except ImportError:
            print(f"  [MISSING] {package} — НЕ УСТАНОВЛЕН")
            all_installed = False

    if not all_installed:
        print("\n[!] Некоторые зависимости отсутствуют.")
        print("Пожалуйста, выполните команду: pip install -r requirements.txt\n")
    else:
        print("\nВсе библиотеки успешно найдены!")

    try:
        importlib.import_module("tensorflow")
        if sys.version_info >= (3, 14):
            print("  [INCOMPATIBLE] TensorFlow stable требует Python 3.10–3.13 для обучения.")
        else:
            print("  [OK] tensorflow — доступен обучающий конвейер")
    except ImportError:
        print("\n[OPTIONAL] TensorFlow не установлен: обычные функции приложения доступны,")
        print("но обучение BiLSTM отключено. Для обучения используйте Python 3.13:")
        print("  pip install -r requirements-train.txt\n")


def main():
    print("=== Инициализация KZH Sign Translator ===")
    create_directories()
    check_dependencies()
    print("\nSetup complete!")


if __name__ == "__main__":
    main()
