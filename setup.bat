@echo off
chcp 65001 > nul
echo === Инициализация KZH Sign Translator (Windows) ===

echo [1/2] Создание папок...
if not exist "data\raw_videos" mkdir "data\raw_videos"
if not exist "models" mkdir "models"
if not exist "external\videos" mkdir "external\videos"

echo   [OK] data/
echo   [OK] models/
echo   [OK] external/
echo   [OK] data/raw_videos/
echo   [OK] external/videos/

echo.
echo [2/2] Проверка зависимостей Python...
python setup.py
