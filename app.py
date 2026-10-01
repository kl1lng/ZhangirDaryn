"""
app.py — Главный Dashboard проекта KZH Sign Language Translator

Локальное Streamlit-приложение для:
    1. Управления проектами жестов (создание, загрузка видео)
    2. Обработки видео через MediaPipe (извлечение ключевых точек)
    3. Обучения BiLSTM-модели
    4. Тестирования распознавания в реальном времени

Запуск: streamlit run app.py
"""

import os
import sys
import json
import time
import shutil
import subprocess
import importlib
import importlib.util
from pathlib import Path

import streamlit as st
import numpy as np

# Добавляем корень проекта в путь импорта
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


def _bump_upload_batch_version(version_key: str) -> None:
    """Mark an actual uploader change so large files aren't re-hashed on reruns."""
    st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1


def _motion_library_stats() -> dict[str, int]:
    """Reload the DB module before reading stats in Streamlit's long-lived process."""
    import src.motion_db as motion_db_module
    return importlib.reload(motion_db_module).library_stats()

# ============================================================
# НАСТРОЙКА СТРАНИЦЫ
# ============================================================
st.set_page_config(
    page_title="KZH Sign Translator",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Motion API нужен и во вкладке «Речь → Жесты», поэтому запускаем его для
# всего приложения, а не только при открытии вкладки 3D-аватара.
try:
    from src.motion_api import ensure_motion_api
    ensure_motion_api()
except OSError as motion_api_error:
    st.warning(f"Локальный motion API недоступен: {motion_api_error}")

# ============================================================
# КАСТОМНЫЕ CSS-СТИЛИ: тёмная тема с бирюзовыми акцентами
# ============================================================
CUSTOM_CSS = """
<style>
    /* --- Импорт шрифта Inter --- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* --- Глобальные стили --- */
    html, body, [class*="css"] {
        font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    }
    .stApp {
        background: radial-gradient(circle at 10% 0%, rgba(0,212,170,0.08), transparent 30%), linear-gradient(180deg, #080b16 0%, #101629 100%);
    }

    /* --- Боковая панель --- */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d0d24 0%, #111133 100%);
        border-right: 1px solid rgba(0, 212, 170, 0.15);
    }
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #00d4aa !important;
    }

    /* --- Заголовки --- */
    h1 { color: #ffffff !important; font-weight: 700 !important; }
    h2, h3 { color: #e0e0e0 !important; font-weight: 600 !important; }

    /* --- Карточки --- */
    .card {
        background: linear-gradient(135deg, rgba(15,15,46,0.9) 0%, rgba(20,20,60,0.8) 100%);
        border: 1px solid rgba(0,212,170,0.2);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 16px;
        backdrop-filter: blur(10px);
        transition: border-color 0.3s ease, transform 0.2s ease;
    }
    .card:hover {
        border-color: rgba(0,212,170,0.5);
        transform: translateY(-1px);
    }

    /* --- Статистика --- */
    .stat-card {
        background: linear-gradient(135deg, rgba(0,212,170,0.08) 0%, rgba(0,212,170,0.03) 100%);
        border: 1px solid rgba(0,212,170,0.25);
        border-radius: 14px;
        padding: 16px;
        text-align: center;
        margin-bottom: 12px;
    }
    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #00d4aa;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 0.8rem;
        color: #8888aa;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 4px;
    }

    /* --- Кнопки --- */
    .stButton > button {
        background: linear-gradient(135deg, #00d4aa 0%, #00b894 100%) !important;
        color: #0a0a1a !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-family: 'Inter', system-ui, sans-serif !important;
        padding: 0.5rem 1.5rem !important;
        transition: all 0.3s ease !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #00e6b8 0%, #00d4aa 100%) !important;
        box-shadow: 0 4px 15px rgba(0,212,170,0.4) !important;
        transform: translateY(-1px) !important;
    }

    /* --- Вкладки --- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(15,15,46,0.5);
        border-radius: 10px;
        padding: 6px;
        border: 1px solid rgba(255,255,255,0.06);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px !important;
        padding: 8px 20px !important;
        color: #8888aa !important;
        font-weight: 500 !important;
        min-height: 42px;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(0,212,170,0.15) !important;
        color: #00d4aa !important;
    }

    /* --- Прогресс-бар --- */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #00d4aa 0%, #00e6b8 100%) !important;
    }

    /* --- Метрики --- */
    [data-testid="stMetricValue"] {
        color: #00d4aa !important;
        font-weight: 700 !important;
    }

    /* --- File uploader --- */
    [data-testid="stFileUploader"] {
        border: 2px dashed rgba(0,212,170,0.3) !important;
        border-radius: 12px !important;
        padding: 20px !important;
    }

    /* --- Успешные/ошибочные сообщения --- */
    .stSuccess { border-left: 4px solid #00d4aa !important; }
    .stError { border-left: 4px solid #ff4757 !important; }

    /* --- Разделитель --- */
    hr { border-color: rgba(0,212,170,0.15) !important; }

    /* --- Скрыть footer Streamlit --- */
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    .brand-mark { color:#00d4aa; font-size:1.1rem; font-weight:700; letter-spacing:.08em; }
    .eyebrow { color:#00d4aa; font-size:.72rem; text-transform:uppercase; letter-spacing:.16em; font-weight:700; }
    .section-title { display:flex; align-items:center; gap:10px; }
    .icon-badge { display:inline-flex; width:30px; height:30px; align-items:center; justify-content:center; border-radius:9px; background:rgba(0,212,170,.12); color:#00d4aa; font-weight:700; }

    /* Apple-inspired dashboard layer */
    .stApp { background:linear-gradient(145deg,#f5f5f7 0%,#e9eef5 100%); color:#1d1d1f; }
    section[data-testid="stSidebar"] { background:rgba(245,245,247,.88); border-right:1px solid #d2d2d7; backdrop-filter:blur(20px); }
    section[data-testid="stSidebar"] .stMarkdown h1, section[data-testid="stSidebar"] .stMarkdown h2, section[data-testid="stSidebar"] .stMarkdown h3 { color:#1d1d1f !important; }
    h1,h2,h3 { color:#1d1d1f !important; letter-spacing:-.035em; }
    .card { background:rgba(255,255,255,.78); border:1px solid rgba(255,255,255,.9); border-radius:20px; box-shadow:0 16px 44px rgba(31,45,61,.10); backdrop-filter:blur(20px); }
    .stat-card { background:rgba(255,255,255,.7); border:1px solid #d2d2d7; border-radius:16px; }
    .stat-number { color:#0071e3; }
    .stat-label { color:#6e6e73; }
    .stButton > button { background:#0071e3 !important; color:#fff !important; border-radius:999px !important; box-shadow:0 7px 18px rgba(0,113,227,.2) !important; }
    .stButton > button:hover { background:#0077ed !important; box-shadow:0 10px 24px rgba(0,113,227,.28) !important; }
    .stTabs [data-baseweb="tab-list"] { background:rgba(255,255,255,.62); border:1px solid #d2d2d7; border-radius:14px; }
    .stTabs [data-baseweb="tab"] { color:#6e6e73 !important; border-radius:10px !important; }
    .stTabs [aria-selected="true"] { background:#e8f2ff !important; color:#0071e3 !important; }
    [data-testid="stMetricValue"] { color:#0071e3 !important; }
    [data-testid="stFileUploader"] { border-color:#b7c9df !important; background:rgba(255,255,255,.5); }
    .stMarkdown, .stCaption, label, p { color:#3a3a3c; }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label { color:#3a3a3c !important; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_data_dir() -> Path:
    """Возвращает Path к директории data/, создаёт если нет."""
    data_dir = Path(config.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_models_dir() -> Path:
    """Возвращает Path к директории models/, создаёт если нет."""
    models_dir = Path(config.MODELS_DIR)
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_projects() -> dict:
    """
    Сканирует data/ и возвращает словарь проектов.
    Каждый проект — это папка в data/ с файлом meta.json.
    
    Возвращает: {folder_name: {"name_kz": "...", "videos": N, "has_landmarks": bool}}
    """
    data_dir = get_data_dir()
    projects = {}

    for item in sorted(data_dir.iterdir()):
        if item.is_dir() and item.name != "raw_videos":
            meta_path = item / "meta.json"
            videos_dir = item / "videos"
            landmarks_path = item / "landmarks.npy"
            landmarks_meta_path = item / "landmarks_meta.json"

            # Считаем видеофайлы
            video_count = 0
            if videos_dir.exists():
                video_count = len([
                    f for f in videos_dir.iterdir()
                    if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv")
                ])

            # Читаем метаданные
            name_kz = item.name
            landmarks_meta = {}
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    name_kz = meta.get("name_kz", item.name)
                except Exception:
                    pass
            if landmarks_meta_path.exists():
                try:
                    with open(landmarks_meta_path, "r", encoding="utf-8") as f:
                        landmarks_meta = json.load(f)
                except (OSError, json.JSONDecodeError):
                    landmarks_meta = {}

            landmarks_data_file = landmarks_meta.get("data_file", "landmarks_raw.npy")
            current_landmarks_path = item / landmarks_data_file
            landmarks_current = (
                landmarks_meta.get("format") == "raw_frame_landmarks"
                and current_landmarks_path.is_file()
            )
            projects[item.name] = {
                "name_kz": name_kz,
                "videos": video_count,
                "has_landmarks": current_landmarks_path.is_file() or landmarks_path.exists(),
                "landmarks_current": landmarks_current,
                "landmarks_path": current_landmarks_path if landmarks_current else landmarks_path,
                "path": item,
            }

    return projects


def create_project(folder_name: str, name_kz: str) -> bool:
    """Создаёт новый проект: папку + meta.json."""
    data_dir = get_data_dir()
    project_dir = data_dir / folder_name
    videos_dir = project_dir / "videos"

    if project_dir.exists():
        return False

    try:
        videos_dir.mkdir(parents=True, exist_ok=True)
        meta = {"name_kz": name_kz, "folder": folder_name}
        with open(project_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Ошибка создания проекта: {e}")
        return False


def count_models() -> int:
    """Считает файлы .h5 в models/."""
    models_dir = get_models_dir()
    return len(list(models_dir.glob("*.h5")))


def render_stat_card(number, label):
    """Рендерит карточку статистики в боковой панели."""
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-number">{number}</div>
        <div class="stat-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# БОКОВАЯ ПАНЕЛЬ
# ============================================================

with st.sidebar:
    st.markdown('<div class="section-title"><span class="icon-badge">▣</span><h2>Проекты</h2></div>', unsafe_allow_html=True)
    st.markdown("---")

    projects = get_projects()

    # --- Создание нового проекта ---
    with st.expander("＋  Новый проект", expanded=False):
        new_folder = st.text_input(
            "Название (латиницей)",
            placeholder="salemet",
            help="Имя папки — только латинские буквы, цифры, подчёркивания",
            key="new_folder_input"
        )
        new_name_kz = st.text_input(
            "Слово на казахском",
            placeholder="сәлем",
            help="Казахское слово/фраза для этого жеста",
            key="new_name_kz_input"
        )
        if st.button("Создать проект", key="btn_create_project"):
            if new_folder and new_name_kz:
                # Очистка имени папки
                clean_folder = "".join(
                    c for c in new_folder if c.isalnum() or c == "_"
                ).lower()
                if clean_folder:
                    if create_project(clean_folder, new_name_kz):
                        st.success(f"Проект «{new_name_kz}» создан!")
                        st.rerun()
                    else:
                        st.warning("Проект с таким именем уже существует.")
                else:
                    st.error("Введите корректное имя (латиница).")
            else:
                st.error("Заполните оба поля.")

    st.markdown("---")

    # --- Список проектов ---
    if projects:
        selected_project = st.radio(
            "Выберите проект:",
            list(projects.keys()),
            format_func=lambda x: f"{'●' if projects[x].get('landmarks_current') else '○'}  {projects[x]['name_kz']}  ·  {projects[x]['videos']} видео",
            key="project_selector",
        )
    else:
        selected_project = None
        st.info("Нет проектов. Создайте первый!")

    st.markdown("---")

    # --- Статистика ---
    st.markdown("### Статистика")
    total_videos = sum(p["videos"] for p in projects.values())
    total_models = count_models()

    col1, col2, col3 = st.columns(3)
    with col1:
        render_stat_card(len(projects), "Проекты")
    with col2:
        render_stat_card(total_videos, "Видео")
    with col3:
        render_stat_card(total_models, "Модели")


# ============================================================
# ГЛАВНАЯ ЗОНА
# ============================================================

# Заголовок
st.markdown("""
<h1 style="text-align:center; margin-bottom:0;">
    <span class="brand-mark">KZH</span> Sign Translator
</h1>
<p style="text-align:center; color:#8888aa; font-size:0.9rem; margin-top:4px; margin-bottom:30px;">
    ИИ-переводчик казахского жестового языка &nbsp;|&nbsp; Aqbobek International School
</p>
""", unsafe_allow_html=True)

# Если проект не выбран — приветственный экран
if selected_project is None:
    st.markdown("""
    <div class="card" style="text-align:center; padding:60px 20px;">
        <h2 style="color:#00d4aa !important;">Добро пожаловать!</h2>
        <p style="color:#aaa; font-size:1.1rem;">
            Создайте первый проект в боковой панели, чтобы начать сбор данных
            и обучение модели распознавания жестов.
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# Информация о текущем проекте
proj = projects[selected_project]
proj_path = proj["path"]
videos_dir = proj_path / "videos"

# ============================================================
# ВКЛАДКИ
# ============================================================
tab_upload, tab_mediapipe, tab_train, tab_test, tab_speech, tab_avatar = st.tabs([
    "⇧  Загрузка видео",
    "◈  Обработка MediaPipe",
    "◇  Обучение модели",
    "□  Тестирование",
    "≋  Речь → Жесты",
    "◉  Аватар",
])


# =============================================================
# ВКЛАДКА 1: Загрузка видео
# =============================================================
with tab_upload:
    st.markdown(f"""
    <div class="card">
        <h3 style="color:#00d4aa !important; margin-top:0;">
            <span class="icon-badge">⇧</span> Загрузка видео — «{proj['name_kz']}»
        </h3>
        <p style="color:#aaa;">
            Загрузите видеозаписи жеста. Рекомендуется 15–30 видео по 1–3 секунды каждое.
            Снимайте с разных ракурсов, при разном освещении — это улучшит качество модели.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # File uploader
    upload_version_key = f"upload_batch_version_{selected_project}"
    processed_version_key = f"processed_upload_batch_version_{selected_project}"
    uploaded_files = st.file_uploader(
        "Перетащите видеофайлы сюда",
        type=["mp4", "mov", "avi"],
        accept_multiple_files=True,
        key=f"uploader_{selected_project}",
        on_change=_bump_upload_batch_version,
        args=(upload_version_key,),
        help="Поддерживаются форматы MP4, MOV, AVI",
    )

    feedback_by_project = st.session_state.setdefault("upload_feedback", {})
    for upload_note in feedback_by_project.pop(selected_project, []):
        st.error(upload_note)

    upload_version = int(st.session_state.get(upload_version_key, 0))
    processed_upload_version = int(st.session_state.get(processed_version_key, 0))
    if upload_version != processed_upload_version:
        st.session_state[processed_version_key] = upload_version
        progress_bar = st.progress(0, text="Загрузка файлов...")
        from src.ingest_manifest import save_uploaded_videos
        saved_paths, save_errors = save_uploaded_videos(uploaded_files or (), videos_dir)
        progress_bar.progress(1.0, text="Загрузка завершена!")
        if saved_paths:
            st.success(f"Видео доступны в проекте: {len(saved_paths)} · `{videos_dir}`")
        if save_errors:
            if saved_paths:
                feedback_by_project[selected_project] = save_errors
            else:
                for save_error in save_errors:
                    st.error(save_error)
        if saved_paths:
            time.sleep(0.3)
            st.rerun()

    # Отображение загруженных видео
    st.markdown("---")
    st.markdown(f"### Загруженные видео ({proj['videos']})")

    if proj["videos"] > 0:
        video_files = sorted([
            f for f in videos_dir.iterdir()
            if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv")
        ])

        # Сетка 3 колонки
        cols = st.columns(3)
        for idx, vf in enumerate(video_files):
            with cols[idx % 3]:
                st.markdown(f"""
                <div class="card" style="padding:10px;">
                    <p style="color:#00d4aa; font-size:0.8rem; margin:0 0 8px 0; font-weight:500;">
                        {vf.name}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                try:
                    st.video(str(vf))
                except Exception:
                    st.caption(f"Видео · {vf.name}")
    else:
        st.info("Пока нет видео. Загрузите файлы выше.")


# =============================================================
# ВКЛАДКА 2: Обработка MediaPipe
# =============================================================
with tab_mediapipe:
    st.markdown(f"""
    <div class="card">
        <h3 style="color:#00d4aa !important; margin-top:0;">
            <span class="icon-badge">◈</span> Обработка MediaPipe — «{proj['name_kz']}»
        </h3>
        <p style="color:#aaa;">
            MediaPipe сохраняет покадровые landmarks обеих рук и доступные точки лица
            в исходной временной длине видео. Для обучения они нормализуются и
            приводятся к форме (30, 162) уже отдельным этапом.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Статистика
    landmarks_path = proj.get("landmarks_path", proj_path / "landmarks.npy")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Видео в проекте", proj["videos"])
    with col2:
        st.metric(
            "Сырые landmarks",
            "Актуальны" if proj.get("landmarks_current") else "Нужно обработать заново" if proj["has_landmarks"] else "Нет",
        )

    if proj["has_landmarks"]:
        if not proj.get("landmarks_current"):
            st.warning(
                "Найдены только landmarks старого формата. Нажмите «Запустить MediaPipe», "
                "чтобы создать отдельный landmarks_raw.npy. Старый landmarks.npy и исходные "
                "видео останутся нетронутыми."
            )
        try:
            existing_lm = np.load(str(landmarks_path), allow_pickle=True)
            if isinstance(existing_lm, np.ndarray) and existing_lm.dtype == object:
                st.info(f"Сырой файл содержит {len(existing_lm)} покадровых клипов переменной длины.")
            else:
                st.info(f"Файл landmarks (старый/фиксированной формы): {existing_lm.shape}")
        except Exception:
            pass

    st.markdown("---")

    if proj["videos"] == 0:
        st.warning("Сначала загрузите видео во вкладке «Загрузка видео».")
    else:
        processing_videos = sorted([
            f for f in videos_dir.iterdir()
            if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv")
        ])
        processing_signers = {}
        publish_motion_recording = st.checkbox(
            "Подтверждаю право добавить эти записи в общую motion-библиотеку (поиск и аватар)",
            key=f"rights_confirmed_project_{selected_project}",
            help="Без подтверждения landmarks останутся внутри проекта и не попадут в общий "
                 "поиск/аватар. Проектный учебный pipeline продолжит работать.",
        )
        project_motion_license = ""
        if publish_motion_recording:
            project_motion_license = st.text_input(
                "Основание использования видео",
                key=f"motion_license_project_{selected_project}",
                placeholder="Например: собственная запись, лицензия CC BY 4.0, письменное разрешение",
                help="Укажите проверяемое основание, а не просто «можно использовать». "
                     "Оно сохранится в карточке жеста в SQLite.",
            ).strip()
            if not project_motion_license:
                st.caption("Укажите основание, чтобы включить запись в общую motion-библиотеку.")
        with st.expander("Исполнители для проверки модели", expanded=False):
            st.caption(
                "Укажите постоянный обезличенный ID одного и того же исполнителя "
                "во всех его роликах (например, signer-01). Не вводите имя человека."
            )
            for video_path in processing_videos:
                processing_signers[video_path.name] = st.text_input(
                    f"ID исполнителя · {video_path.name}",
                    key=f"project_signer_{selected_project}_{video_path.name}",
                    placeholder="например, signer-01",
                ).strip()
        if st.button(
            "Запустить MediaPipe", key="btn_mediapipe",
            disabled=publish_motion_recording and not project_motion_license,
        ):
            try:
                # Import and reload the canonical motion pipeline. When the
                # uploader confirms reuse rights, one extraction feeds both
                # project training data and the searchable SQLite library.
                import importlib
                import src.motion_db
                import src.extract_landmarks
                import src.normalize
                importlib.reload(src.motion_db)
                importlib.reload(src.extract_landmarks)
                importlib.reload(src.normalize)

                from src.extract_landmarks import extract_from_video
                from src.motion_db import get_motion_clip, import_video_motion
                video_files = processing_videos

                all_sequences = []
                processed_video_names = []
                motion_import_count = 0
                progress_bar = st.progress(0, text="Подготовка...")
                status_text = st.empty()
                total = len(video_files)

                for i, vf in enumerate(video_files):
                    status_text.markdown(
                        f"**Обработка:** `{vf.name}` ({i + 1}/{total})"
                    )
                    progress_bar.progress(
                        (i + 1) / total,
                        text=f"Обработка видео {i + 1}/{total}..."
                    )

                    if publish_motion_recording:
                        clip_id = import_video_motion(
                            proj["name_kz"], vf, phrase=proj["name_kz"],
                            source="local-project-upload",
                            license_name=project_motion_license,
                            signer_id=processing_signers.get(vf.name) or None,
                            rights_confirmed=True,
                        )
                        stored_clip = get_motion_clip(clip_id)
                        if stored_clip is None:
                            raise RuntimeError(
                                f"Импортированный motion-клип {clip_id} не удалось перечитать из SQLite"
                            )
                        motion_import_count += 1
                        landmarks = stored_clip["sequence"].tolist() if stored_clip else []
                    else:
                        # Project-local training remains available without
                        # publishing to the shared/searchable motion library.
                        landmarks = extract_from_video(str(vf))

                    if len(landmarks) > 0:
                        # Сохраняем сырые кадры переменной длины. Нормализация
                        # происходит один раз при сборке train/inference-входа.
                        seq = np.asarray(landmarks, dtype=np.float32)
                        hand_points = seq[:, :config.HAND_FEATURES].reshape(
                            -1, config.NUM_HANDS, config.NUM_LANDMARKS, config.COORDS_PER_LANDMARK
                        )
                        wrist = hand_points[:, :, :1, :2]
                        extent = np.linalg.norm(hand_points[:, :, 1:, :2] - wrist, axis=-1).max(axis=2)
                        visible_frames = np.any(extent > 0.012, axis=1)
                        min_visible = max(3, int(np.ceil(len(seq) * 0.1)))
                        if int(visible_frames.sum()) >= min_visible:
                            all_sequences.append(seq)
                            processed_video_names.append(vf.name)
                        else:
                            st.warning(
                                f"Слишком мало кадров с руками ({int(visible_frames.sum())}/{len(seq)}): {vf.name}"
                            )
                    else:
                        st.warning(f"Рука не найдена: {vf.name}")

                progress_bar.progress(1.0, text="Обработка завершена!")

                if all_sequences:
                    # Сохраняем клипы разной длины без потери временной динамики.
                    result = np.empty(len(all_sequences), dtype=object)
                    result[:] = all_sequences
                    raw_landmarks_path = proj_path / "landmarks_raw.npy"
                    np.save(str(raw_landmarks_path), result, allow_pickle=True)
                    landmarks_path = raw_landmarks_path
                    with open(proj_path / "landmarks_meta.json", "w", encoding="utf-8") as meta_file:
                        json.dump({
                            "format": "raw_frame_landmarks",
                            "data_file": raw_landmarks_path.name,
                            "coordinate_space": "mediapipe_normalized_image",
                            "feature_count": config.TOTAL_FEATURES,
                            "extractor": "mediapipe-hand-landmarker",
                            "rights_confirmed": bool(publish_motion_recording),
                            "source_videos": [str(Path("videos") / name) for name in processed_video_names],
                            "signer_ids": {
                                name: processing_signers.get(name) or None
                                for name in processed_video_names
                            },
                        }, meta_file, ensure_ascii=False, indent=2)

                    status_text.empty()
                    st.success(
                        f"Обработка завершена! Сохранено {len(all_sequences)} "
                        f"из {total} видео. "
                        + (f"{motion_import_count} клипов добавлено в motion-поиск и аватар. "
                           if publish_motion_recording else "Клипы оставлены внутри учебного проекта. ")
                        + f"Формы клипов: {[list(seq.shape) for seq in all_sequences]}"
                    )

                    # Кнопка скачивания
                    with open(str(landmarks_path), "rb") as f:
                        st.download_button(
                            label="⬇️ Скачать сырые landmarks",
                            data=f.read(),
                            file_name=f"{selected_project}_landmarks_raw.npy",
                            mime="application/octet-stream",
                            key="download_landmarks",
                        )
                else:
                    st.error("Не удалось извлечь данные ни из одного видео.")

            except ImportError as e:
                st.error(
                    f"Ошибка импорта: {e}. "
                    "Убедитесь, что установлены mediapipe и opencv-python: "
                    "`pip install mediapipe opencv-python`"
                )
            except Exception as e:
                st.error(f"Ошибка обработки: {type(e).__name__}: {e}")


# =============================================================
# ВКЛАДКА 3: Обучение модели
# =============================================================
with tab_train:
    st.markdown("""
    <div class="card">
        <h3 style="color:#00d4aa !important; margin-top:0;">
            Обучение BiLSTM-модели
        </h3>
        <p style="color:#aaa;">
            Модель обучается на видео-последовательностях из проектов и motion-базы.
            Validation разделяет целые группы исполнителей (или исходные видео, если ID не задан).
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Таблица готовых проектов
    ready_projects = {
        k: v for k, v in projects.items() if v.get("landmarks_current")
    }
    stale_projects = [v["name_kz"] for v in projects.values()
                      if v["has_landmarks"] and not v.get("landmarks_current")]
    from src.training_data import collect_training_sequences, prepare_training_data
    training_sequences_by_label, training_counts, training_groups_by_label = collect_training_sequences(
        projects, include_groups=True
    )

    st.markdown("### Готовые проекты")

    if ready_projects:
        table_data = []
        for folder, info in ready_projects.items():
            # Пробуем прочитать форму landmarks
            lm_path = info.get("landmarks_path", info["path"] / "landmarks.npy")
            shape_str = "—"
            sample_count = 0
            try:
                lm = np.load(str(lm_path), allow_pickle=True)
                shape_str = str(lm.shape)
                sample_count = lm.shape[0] if lm.ndim >= 1 else 0
            except Exception:
                pass

            table_data.append({
                "Слово": info["name_kz"],
                "Папка": folder,
                "Примеров": sample_count,
                "Форма": shape_str,
                "Статус": "Готов",
            })

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Нет проектов с обработанными landmarks. Обработайте видео во вкладке «Обработка MediaPipe».")
    if stale_projects:
        st.warning(
            "Проекты со старым форматом landmarks (исключены из обучения до повторной обработки): "
            + ", ".join(stale_projects)
        )

    st.markdown("### Motion-клипы, включённые в датасет")
    if training_counts:
        st.dataframe(
            [{"Класс": label, "Видео": count,
              "Групп для независимой проверки": len(set(training_groups_by_label.get(label, []))),
              "Статус": "Готов к проверке" if len(set(training_groups_by_label.get(label, []))) >= 2 else "Нужны другие исполнители/источники"}
             for label, count in training_counts.items()],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Нет размеченных последовательностей ни в проектах, ни в motion-базе.")

    st.markdown("---")

    # Обучение
    eligible_classes = {
        label: count for label, count in training_counts.items()
        if count >= 2 and len(set(training_groups_by_label.get(label, []))) >= 2
    }
    tensorflow_available = (
        sys.version_info < (3, 14)
        and importlib.util.find_spec("tensorflow") is not None
    )
    if not tensorflow_available:
        current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        st.info(
            f"Обучающий backend TensorFlow сейчас недоступен (Python {current_python}). "
            "Для обучения нужна отдельная среда Python 3.13 с `requirements-train.txt`; "
            "motion-библиотека и остальные вкладки работают без TensorFlow."
        )
    if len(training_counts) < 2 or len(eligible_classes) != len(training_counts):
        st.warning(
            "Нужны минимум 2 класса и по 2 независимые группы на класс. "
            "Если заданы signer ID, все видео одного исполнителя попадут в одну группу; "
            "без ID группой считается исходный видеофайл. Копии источника не считаются отдельными примерами."
        )
    elif not tensorflow_available:
        st.warning(
            "TensorFlow для обучения недоступен в текущем окружении. "
            "Установите зависимости в Python 3.13 (стабильные версии TensorFlow поддерживают Python 3.10–3.13)."
        )
    else:
        # Параметры обучения
        st.markdown("### Параметры обучения")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            epochs = st.number_input("Эпохи", min_value=5, max_value=200, value=50, step=5)
        with col2:
            batch_size = st.selectbox("Размер батча", [4, 8, 16, 32], index=2)
        with col3:
            val_split = st.slider("Валидация (%)", 10, 40, 20, 5)
        with col4:
            aug_factor = st.selectbox("Аугментация ИИ", [1, 3, 5], format_func=lambda x: "Отключена" if x == 1 else f"Увеличить {x}x")

        st.markdown("---")

        if st.button("Обучить BiLSTM", key="btn_train", type="primary"):
            try:
                with st.spinner("Подготовка данных и обучение модели. Это может занять 1–3 минуты..."):
                    X, y, label_map, training_groups = prepare_training_data(
                        training_sequences_by_label,
                        groups_by_label=training_groups_by_label,
                    )
                    if len(X) == 0 or len(label_map) < 2:
                        st.error("Не удалось загрузить данные из landmarks.")
                        st.stop()
                    num_classes = len(label_map)

                    # Вызываем модуль обучения из src.train
                    import importlib
                    import src.train
                    importlib.reload(src.train)
                    from src.train import train_model, save_model_and_labels

                    model, history = train_model(
                        X, y,
                        num_classes=num_classes,
                        epochs=epochs,
                        batch_size=batch_size,
                        validation_split=val_split / 100,
                        augment_factor=aug_factor,
                        groups=training_groups,
                    )

                    if model is None or history is None:
                        st.error("Обучение не завершилось; модель не сохранена.")
                        st.stop()

                # Результаты
                final_acc = history.history["accuracy"][-1]
                final_val_acc = history.history["val_accuracy"][-1]

                # Метрики
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Accuracy (train)", f"{final_acc * 100:.1f}%")
                with col2:
                    st.metric("Accuracy (val)", f"{final_val_acc * 100:.1f}%")
                with col3:
                    st.metric("Loss (train)", f"{history.history['loss'][-1]:.4f}")
                with col4:
                    st.metric("Эпох", len(history.history["accuracy"]))

                # Графики
                st.markdown("### Графики обучения")
                gcol1, gcol2 = st.columns(2)
                with gcol1:
                    st.line_chart(
                        {
                            "Обучение": history.history["accuracy"],
                            "Валидация": history.history["val_accuracy"],
                        },
                        use_container_width=True,
                    )
                    st.caption("Точность (Accuracy)")
                with gcol2:
                    st.line_chart(
                        {
                            "Обучение": history.history["loss"],
                            "Валидация": history.history["val_loss"],
                        },
                        use_container_width=True,
                    )
                    st.caption("Ошибка (Loss)")

                # Сохранение
                models_dir = get_models_dir()
                model_path = models_dir / "sign_model.h5"
                label_map_path = models_dir / "label_map.json"
                save_model_and_labels(
                    model, label_map,
                    model_path=str(model_path),
                    map_path=str(label_map_path),
                    training_metadata={
                        "validation_strategy": "grouped_by_signer_or_source",
                        "validation_split": val_split / 100,
                        "groups_by_class": {
                            label: len(set(training_groups_by_label.get(label, [])))
                            for label in label_map
                        },
                        "validation_accuracy": float(final_val_acc),
                        "sample_count": int(len(X)),
                    },
                )

                st.success(
                    f"Обучение и сохранение завершены за {len(history.history['accuracy'])} эпох!"
                )
                st.info(f"Модель сохранена: `{model_path}`")

                # Кнопка скачивания модели
                with open(str(model_path), "rb") as f:
                    st.download_button(
                        label="⬇️ Скачать model.h5",
                        data=f.read(),
                        file_name="sign_model.h5",
                        mime="application/octet-stream",
                        key="download_model",
                    )

            except ImportError as e:
                st.error(
                    f"Ошибка импорта: {e}. "
                    "Убедитесь, что установлен tensorflow: `pip install tensorflow`"
                )
            except Exception as e:
                st.error(f"Ошибка обучения: {type(e).__name__}: {e}")


# =============================================================
# ВКЛАДКА 4: Тестирование
# =============================================================
with tab_test:
    st.markdown("""
    <div class="card">
        <h3 style="color:#00d4aa !important; margin-top:0;">
            Live-тест жестов с веб-камеры
        </h3>
        <p style="color:#aaa;">
            Анализируется временная последовательность кадров, а не одиночный снимок.
            С обученной BiLSTM показывается предсказанный класс; без неё — только ближайший
            пример из motion-базы, без заявления об уверенном распознавании.
        </p>
    </div>
    """, unsafe_allow_html=True)

    models_dir = get_models_dir()
    model_path = models_dir / "sign_model.h5"
    label_map_path = models_dir / "label_map.json"
    model_runtime_ready = (
        model_path.is_file()
        and label_map_path.is_file()
        and importlib.util.find_spec("tensorflow") is not None
    )

    if not model_path.exists():
        motion_stats = _motion_library_stats()
        if motion_stats["stored_clips"] != motion_stats["clips"]:
            st.caption(
                "В motion-поиске доступно "
                f"{motion_stats['clips']} пригодных клипа; в хранилище — "
                f"{motion_stats['stored_clips']} записей из "
                f"{motion_stats['unique_sources']} уникальных видеоисточников."
            )
        if motion_stats["clips"]:
            st.info(
                f"Обученной модели пока нет. Доступен live-режим сравнения с motion-примерами "
                f"({motion_stats['clips']} клипа, {motion_stats['gestures']} класса). "
                "При одном классе система не будет подписывать наблюдение его меткой; "
                "для сравнения нужны видео минимум двух разных жестов."
            )
            live_process = st.session_state.get("dosym_camera_process")
            if live_process is not None and live_process.poll() is None:
                st.success("Окно веб-камеры запущено. Нажмите Q в окне видео, чтобы завершить.")
            elif st.button("Запустить live-камеру", key="start_motion_camera", type="primary"):
                try:
                    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    st.session_state["dosym_camera_process"] = subprocess.Popen(
                        [sys.executable, str(Path(config.BASE_DIR) / "src" / "predict.py")],
                        cwd=str(config.BASE_DIR),
                        creationflags=flags,
                    )
                    st.success("Окно веб-камеры запускается. Нажмите Q в окне видео, чтобы завершить.")
                except OSError as camera_error:
                    st.error(f"Не удалось запустить локальную камеру: {camera_error}")
        else:
            st.warning("Нет ни обученной модели, ни сохранённых motion-клипов. Добавьте видео и обработайте его.")
    else:
        # Загружаем label_map
        reverse_map = {}
        label_map_compatible = False
        if label_map_path.exists():
            try:
                from src.training_utils import load_label_map
                reverse_map = load_label_map(label_map_path)
                label_map_compatible = True
                with open(label_map_path, "r", encoding="utf-8") as map_stream:
                    model_metadata = json.load(map_stream).get("training")
                st.info(f"Модель загружена. Распознаёт {len(reverse_map)} жестов: {', '.join(reverse_map.values())}")
                if not isinstance(model_metadata, dict):
                    st.warning(
                        "Для этой модели не сохранена схема validation. Её качество "
                        "не подтверждено проверкой на независимых исполнителях/источниках."
                    )
                elif model_metadata.get("validation_strategy") != "grouped_by_signer_or_source":
                    st.warning("Модель обучена без группового разделения по исполнителю/источнику.")
            except (OSError, ValueError, json.JSONDecodeError) as label_error:
                st.warning(f"Карта меток несовместима с текущими признаками: {label_error}")
        model_runtime_ready = label_map_compatible and importlib.util.find_spec("tensorflow") is not None
        motion_stats = _motion_library_stats()
        if motion_stats["stored_clips"] != motion_stats["clips"]:
            st.caption(
                "В motion-поиске доступно "
                f"{motion_stats['clips']} пригодных клипа; в хранилище — "
                f"{motion_stats['stored_clips']} записей из "
                f"{motion_stats['unique_sources']} уникальных видеоисточников."
            )
        if model_runtime_ready:
            st.success(f"Обученная live-модель готова · жестов: {len(reverse_map)}")
        elif motion_stats["clips"]:
            st.info(
                f"Будет использовано сравнение live-последовательности с motion-примерами "
                f"({motion_stats['clips']} клипа, {motion_stats['gestures']} класса); "
                "это поиск ближайшего шаблона, не обученный классификатор."
            )
        else:
            st.warning("Нет доступной обученной модели или motion-клипов для live-сравнения.")

        # The classifier consumes a temporal window: capture live frames rather
        # than padding a single still image into a fake 30-frame gesture.
        live_process = st.session_state.get("dosym_camera_process")
        if live_process is not None and live_process.poll() is None:
            st.success("Окно веб-камеры запущено. Нажмите Q в окне видео, чтобы завершить.")
        elif st.button(
            "Запустить live-камеру", key="start_motion_camera", type="primary",
            disabled=not (model_runtime_ready or motion_stats["clips"]),
        ):
            try:
                flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                st.session_state["dosym_camera_process"] = subprocess.Popen(
                    [sys.executable, str(Path(config.BASE_DIR) / "src" / "predict.py")],
                    cwd=str(config.BASE_DIR),
                    creationflags=flags,
                )
                st.success("Окно веб-камеры запускается. Нажмите Q в окне видео, чтобы завершить.")
            except OSError as camera_error:
                st.error(f"Не удалось запустить локальную камеру: {camera_error}")
        st.caption(
            "Классификатор анализирует непрерывные 30 кадров веб-камеры. "
            "Одиночный снимок не выдаётся за последовательность жеста."
        )
# =============================================================
# ВКЛАДКА 5: Речь → Жесты (Обратный перевод)
# =============================================================
with tab_speech:
    st.markdown("""
    <div class="card">
        <h3 style="color:#00d4aa !important; margin-top:0;">
            Обратный перевод: Речь → Жесты
        </h3>
        <p style="color:#aaa;">
            Распознавание казахской речи через Web Speech API и воспроизведение проверенных motion-клипов из локальной базы. Для слов без клипа показывается явное предупреждение вместо фиктивного дактиля.
        </p>
    </div>
    """, unsafe_allow_html=True)

    html_file_path = Path(config.BASE_DIR) / "web" / "index.html"
    if html_file_path.exists():
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        import streamlit.components.v1 as components
        components.html(html_content, height=800, scrolling=True)
    else:
        st.error(f"Файл не найден: `{html_file_path}`")


# =============================================================
# ВКЛАДКА 6: Демонстрационный аватар
# =============================================================
with tab_avatar:
    st.markdown("""
    <div class="card">
        <h3 style="margin-top:0;">3D-проигрыватель жестов</h3>
        <p>Покадрово воспроизводит движения пальцев и запястья, извлечённые из видео и сохранённые в motion-базе.</p>
    </div>
    """, unsafe_allow_html=True)
    avatar_path = Path(config.BASE_DIR) / "web" / "avatar.html"
    if avatar_path.exists():
        import streamlit.components.v1 as components
        avatar_html = avatar_path.read_text(encoding="utf-8")
        motion_sequence = []
        motion_queue = []
        motion_missing = []
        phrase = ""
        motion_language = "kk-KZ"
        gesture_names = []
        motion_fps = 30.0
        try:
            import importlib
            importlib.reload(config)
            import src.motion_db as motion_db_module
            motion_db_module = importlib.reload(motion_db_module)
            compose_phrase_segments = motion_db_module.compose_phrase_segments
            clip_tracking_eligible = motion_db_module.clip_tracking_eligible
            connect = motion_db_module.connect
            library_stats = motion_db_module.library_stats
            library_coverage = motion_db_module.library_coverage
            available_search_terms = motion_db_module.available_search_terms
            find_gesture = motion_db_module.find_gesture
            stats = library_stats()
            st.caption(
                f"Motion-библиотека: {stats['gestures']} жестов · "
                f"{stats['clips']} клипов для поиска · "
                f"{stats['stored_clips']} записей / {stats['unique_sources']} уникальных источников"
            )
            coverage_rows = library_coverage()
            if coverage_rows:
                st.dataframe(
                    [{
                        "Язык": row["language"],
                        "Метки в каталоге": row["catalog_gestures"],
                        "Жестов с пригодным клипом": row["gestures"],
                        "Без пригодного клипа": ", ".join(row["uncovered_gestures"]) or "—",
                        "Пригодных видео": row["eligible_clips"],
                        "Групп проверки (signer ID / видео)": row["validation_groups"],
                        "Клипов с позой верхней части тела": row["body_pose_clips"],
                    } for row in coverage_rows],
                    use_container_width=True,
                    hide_index=True,
                )
            motion_language = st.selectbox(
                "Язык вводимой фразы",
                options=("kk-KZ", "ru-RU"),
                format_func=lambda value: "Қазақша" if value == "kk-KZ" else "Русский",
                key="motion_phrase_language",
            )
            gesture_names = available_search_terms(motion_language)
            if gesture_names:
                st.caption("Доступные названия и проверенные переводы: " + ", ".join(gesture_names))
            else:
                st.info("Для этого языка пока нет проверенных меток/переводов с пригодным motion-клипом.")
            with connect() as motion_db:
                clip_rows = motion_db.execute(
                    """SELECT c.id, g.lemma, c.source_video, c.frame_count, c.fps,
                              c.start_frame, c.end_frame,
                              c.metadata_json, g.source, g.license
                       FROM gestures g JOIN motion_clips c ON c.gesture_id=g.id
                       ORDER BY g.lemma, c.id DESC"""
                ).fetchall()
            if clip_rows:
                with st.expander("Клипы и качество источников", expanded=False):
                    for clip_id, lemma, source_video, frame_count, fps, start_frame, end_frame, metadata_json, source_name, license_name in clip_rows:
                        metadata = json.loads(metadata_json or "{}")
                        video_name = Path(source_video).name if source_video else "landmarks-файл"
                        coverage = metadata.get("hand_detection_coverage")
                        quality = f" · руки найдены в {coverage:.0%} кадров" if coverage is not None else " · качество трекинга не указано"
                        face_coverage = metadata.get("face_detection_coverage")
                        face_quality = (
                            f" · лицо: {face_coverage:.0%} кадров"
                            if face_coverage is not None else " · лицо не отслеживалось"
                        )
                        body_coverage = metadata.get("body_pose_coverage")
                        body_quality = (
                            f" · плечи/локти/запястья: {body_coverage:.0%} кадров"
                            if body_coverage is not None else " · pose-покрытие тела не записано"
                        )
                        eligible = clip_tracking_eligible(metadata)
                        eligibility = (
                            " · ИСКЛЮЧЁН из текстового перевода, обучения и live-сравнения: "
                            "низкое/некорректное покрытие рук"
                            if not eligible else " · пригоден для playback"
                        )
                        if eligible and coverage is None:
                            eligibility = " · качество трекинга неизвестно (legacy; playback разрешён)"
                        clip_type = "raw motion" if metadata.get("raw_video") else "landmarks"
                        time_range = ""
                        if metadata.get("clip_start_seconds") is not None:
                            start_time = float(metadata["clip_start_seconds"])
                            end_time = metadata.get("clip_end_seconds")
                            time_range = (
                                f" · {start_time:.2f}–{float(end_time):.2f} сек."
                                if end_time is not None else f" · с {start_time:.2f} сек."
                            )
                        st.caption(
                            f"{lemma} · {video_name} · {frame_count} кадров / {fps:g} FPS · "
                            f"кадры [{start_frame}, {end_frame if end_frame is not None else 'конец'}){time_range} · "
                            f"{clip_type}{quality}{face_quality}{body_quality}{eligibility} · источник: {source_name or 'не указан'} · "
                            f"лицензия: {license_name or 'не указана'}"
                        )
                        if source_video and st.button(
                            f"Показать исходное видео · {video_name}",
                            key=f"preview_motion_source_{clip_id}",
                        ):
                            source_path = Path(source_video).expanduser()
                            if not source_path.is_absolute():
                                source_path = Path(config.BASE_DIR) / source_path
                            source_path = source_path.resolve()
                            if source_path.is_file():
                                st.video(str(source_path))
                            else:
                                st.warning(
                                    f"Исходное видео не найдено: {source_path}. "
                                    "Landmarks и анимация аватара остаются доступны из базы."
                                )
            with st.form("motion_phrase_form", clear_on_submit=False):
                phrase = st.text_input(
                    "Текстовая фраза для аватара",
                    value=gesture_names[0] if gesture_names else "",
                    placeholder="Например: сәлем / Привет",
                    key="motion_phrase_input",
                )
                st.form_submit_button("Собрать жестовую фразу")
            segments, found_words, missing_words = compose_phrase_segments(
                phrase, language=motion_language
            )
            motion_queue = [
                {
                    "type": "motion",
                    "label": segment["label"],
                    "sequence": segment["sequence"].astype(float).tolist(),
                    "body_pose": segment.get("metadata", {}).get("body_pose_landmarks"),
                    "image_aspect_ratio": segment.get("metadata", {}).get("image_aspect_ratio"),
                    "language": motion_language,
                    "fps": float(segment["fps"]),
                }
                for segment in segments if segment["type"] == "motion"
            ]
            motion_missing = missing_words
            if found_words:
                st.success(f"Найдены motion-клипы: {', '.join(found_words)}")
                with st.expander("Проверить источники выбранных жестов", expanded=False):
                    provenance_rows = []
                    for segment in segments:
                        if segment.get("type") != "motion":
                            continue
                        metadata = segment.get("metadata") or {}
                        source_path = segment.get("source_video") or ""
                        start_time = metadata.get("clip_start_seconds")
                        end_time = metadata.get("clip_end_seconds")
                        provenance_rows.append({
                            "Жест": segment["label"],
                            "Клип БД": segment["clip_id"],
                            "Источник": Path(source_path).name if source_path else "landmarks без видео",
                            "Интервал, сек.": (
                                f"{float(start_time):.2f}–{float(end_time):.2f}"
                                if start_time is not None and end_time is not None else "—"
                            ),
                            "Кадров / FPS": f"{len(segment['sequence'])} / {float(segment['fps']):g}",
                            "Руки": (
                                f"{float(metadata['hand_detection_coverage']):.0%}"
                                if metadata.get("hand_detection_coverage") is not None else "неизвестно"
                            ),
                            "Корпус": (
                                f"{float(metadata['body_pose_coverage']):.0%}"
                                if metadata.get("body_pose_coverage") is not None else "нет pose-дорожки"
                            ),
                        })
                    st.dataframe(provenance_rows, use_container_width=True, hide_index=True)
            if missing_words:
                st.warning(f"В базе пока нет жестов: {', '.join(missing_words)}")
            project_videos = sorted(
                p for p in (proj_path / "videos").glob("*")
                if p.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}
            )
            if project_videos:
                with st.expander("Импортировать ролики в motion-базу", expanded=False):
                    selected_video_names = st.multiselect(
                        "Видео для импорта (метка задаётся отдельно для каждого ролика)",
                        options=[video.name for video in project_videos],
                        default=[],
                        key=f"motion_video_selection_{selected_project}",
                    )
                    motion_labels = {}
                    for video_name in selected_video_names:
                        motion_labels[video_name] = st.text_input(
                            f"Точная фраза / gloss · {video_name}",
                            value=proj["name_kz"],
                            key=f"motion_label_{selected_project}_{video_name}",
                            help="Укажите соответствующий этому видео жест; по этой метке API будет искать его в тексте.",
                        )
                    motion_source = st.text_input(
                        "Источник видео",
                        value="project-video",
                        key=f"motion_source_{selected_project}",
                    )
                    motion_license = st.text_input(
                        "Лицензия / разрешение / основание использования",
                        value="",
                        key=f"motion_license_{selected_project}",
                    )
                    motion_signer = st.text_input(
                        "Обезличенный ID исполнителя (постоянный для его видео)",
                        key=f"motion_signer_{selected_project}",
                        placeholder="например, signer-01",
                        help="Не указывайте имя. Одинаковый ID на разных видео помогает проверить работу модели на новых исполнителях.",
                    ).strip() or None
                    motion_input_mirrored = st.checkbox(
                        "Видео зеркально отражено по горизонтали",
                        value=False,
                        key=f"motion_input_mirrored_{selected_project}",
                        help="Для обычного видео оставьте выключенным. Используйте только если сам файл, а не предпросмотр, сохранён как selfie-зеркало.",
                    )
                    usage_rights_confirmed = st.checkbox(
                        "Подтверждаю, что имею право использовать выбранные видео для обработки и обучения",
                        value=False,
                        key=f"motion_rights_{selected_project}",
                    )
                    st.caption("Укажите источник (например, AI-Ym) и основание разрешения. Неизменённые ролики не будут анализироваться повторно.")
                    labels_complete = all(label.strip() for label in motion_labels.values())
                    if selected_video_names and labels_complete and motion_license.strip() and usage_rights_confirmed and st.button(
                        "Импортировать выбранные motion-клипы",
                        key=f"import_motion_{selected_project}",
                    ):
                        from src.motion_db import import_video_motion
                        progress = st.progress(0, text="Извлекаю покадровые координаты для аватара…")
                        imported = 0
                        selected_videos = [video for video in project_videos if video.name in selected_video_names]
                        for index, video_path in enumerate(selected_videos):
                            try:
                                motion_label = motion_labels[video_path.name].strip()
                                import_video_motion(
                                    motion_label, video_path,
                                    phrase=motion_label, source=motion_source.strip() or "project-video",
                                    license_name=motion_license.strip() or None,
                                    signer_id=motion_signer,
                                    input_mirrored=motion_input_mirrored,
                                )
                                imported += 1
                            except Exception as import_error:
                                st.error(f"{video_path.name}: {import_error}")
                            progress.progress((index + 1) / len(selected_videos))
                        st.success(f"Motion-клипов обновлено: {imported}")
                        st.rerun()
                    elif selected_video_names and not labels_complete:
                        st.warning("Укажите отдельную непустую метку для каждого выбранного видео.")
                    elif selected_video_names and not motion_license.strip():
                        st.warning("Укажите лицензию, разрешение или основание использования источника.")
                    elif selected_video_names and not usage_rights_confirmed:
                        st.warning("Для импорта подтвердите право на использование выбранных видео.")
            else:
                selected_video_names = []
                motion_labels = {}
                motion_source = "project-video"
                motion_license = ""
            with st.expander("Пакетный импорт CSV с метками и правами", expanded=False):
                st.caption(
                    "Выберите сразу много видео и CSV с точной меткой каждого клипа. "
                    "Сначала сохраните видео в проект, затем загрузите CSV: относительные "
                    "пути в нём считаются от папки videos. Указывайте только проверенные gloss "
                    "и переводы; пустое поле translations безопаснее догадки. "
                    "Импорт в motion-базу запускается отдельно."
                )
                manifest_template = (
                    "video_path,phrase,aliases,translations,source,license,rights_confirmed,signer_id,language,input_mirrored,start_seconds,end_seconds\n"
                    "A73_1.mp4,сәлем,,,project-video,REPLACE_WITH_PERMISSION_OR_LICENSE,no,signer-001,kk-KZ,false,,\n"
                )
                st.download_button(
                    "Скачать CSV-шаблон",
                    data=manifest_template.encode("utf-8"),
                    file_name="motion_manifest.csv",
                    mime="text/csv",
                    key=f"download_manifest_template_{selected_project}",
                )
                uploaded_motion_videos = st.file_uploader(
                    "Видео для пакетного импорта (можно выбрать несколько)",
                    type=["mp4", "mov", "avi", "mkv"],
                    accept_multiple_files=True,
                    key=f"motion_batch_videos_{selected_project}",
                )
                if uploaded_motion_videos and st.button(
                    f"Сохранить выбранные видео ({len(uploaded_motion_videos)}) в проект",
                    key=f"save_motion_batch_{selected_project}",
                ):
                    from src.ingest_manifest import save_uploaded_videos
                    saved_videos, save_errors = save_uploaded_videos(
                        uploaded_motion_videos, proj_path / "videos"
                    )
                    st.success(f"Видео доступны для манифеста: {len(saved_videos)}")
                    for save_error in save_errors:
                        st.error(save_error)
                    if saved_videos:
                        st.rerun()
                manifest_file = st.file_uploader(
                    "CSV-манифест",
                    type=["csv"],
                    key=f"motion_manifest_upload_{selected_project}",
                )
                if manifest_file is not None:
                    from src.ingest_manifest import import_manifest, read_manifest_text
                    try:
                        manifest_text = manifest_file.getvalue().decode("utf-8-sig")
                        manifest_rows, manifest_errors = read_manifest_text(
                            manifest_text, base_dir=proj_path / "videos"
                        )
                    except UnicodeDecodeError:
                        manifest_rows, manifest_errors = [], ["CSV должен быть в кодировке UTF-8."]
                    if manifest_rows:
                        st.dataframe([
                            {
                                "Фраза / gloss": row.phrase,
                                "Проверенные варианты написания": "; ".join(row.aliases),
                                "Переводы для поиска": "; ".join(
                                    f"{language}={text}" for language, text in row.translations
                                ),
                                "Видео": row.video_path.name,
                                "Начало, сек.": row.start_seconds,
                                "Конец, сек.": row.end_seconds if row.end_seconds is not None else "до конца",
                                "Исполнитель": row.signer_id or "не указан",
                                "Видео зеркальное": "да" if row.input_mirrored else "нет",
                                "Источник": row.source,
                                "Основание": row.license_name,
                            }
                            for row in manifest_rows
                        ], use_container_width=True, hide_index=True)
                        st.success(f"Проверено корректных клипов: {len(manifest_rows)}")
                    for manifest_error in manifest_errors:
                        st.warning(manifest_error)
                    if manifest_rows and st.button(
                        f"Импортировать проверенные клипы ({len(manifest_rows)})",
                        key=f"apply_motion_manifest_{selected_project}",
                        type="primary",
                    ):
                        import_progress = st.progress(0.0, text="Подготовка пакета…")

                        def report_import_progress(completed, total, row):
                            import_progress.progress(
                                completed / max(total, 1),
                                text=f"Обработка {completed}/{total}: {row.video_path.name}",
                            )

                        imported, failures = import_manifest(
                            manifest_rows, progress=report_import_progress
                        )
                        for row, clip_id in imported:
                            st.write(f"✓ {row.phrase} · {row.video_path.name} · clip {clip_id}")
                        for row, error in failures:
                            st.error(f"{row.video_path.name}: {error}")
                        st.success(f"Импорт завершён: {len(imported)} успешно, {len(failures)} ошибок.")
                        if imported:
                            st.rerun()
        except Exception as motion_error:
            st.warning(f"Motion-база пока недоступна: {motion_error}")
        avatar_html = avatar_html.replace(
            "__MOTION_SEQUENCE__", json.dumps(motion_sequence, ensure_ascii=False)
        )
        avatar_html = avatar_html.replace(
            "__MOTION_LABEL__", json.dumps(phrase if gesture_names else "", ensure_ascii=False)
        )
        avatar_html = avatar_html.replace("__MOTION_FPS__", str(motion_fps))
        avatar_html = avatar_html.replace(
            "/*IMAGE_ASPECT_RATIO__*/1",
            json.dumps(motion_queue[0].get("image_aspect_ratio") or 1 if motion_queue else 1),
        )
        avatar_html = avatar_html.replace(
            "/*MOTION_QUEUE__*/[]", json.dumps(motion_queue, ensure_ascii=False, separators=(",", ":"))
        )
        avatar_html = avatar_html.replace(
            "/*MOTION_MISSING__*/[]", json.dumps(motion_missing, ensure_ascii=False, separators=(",", ":"))
        )
        avatar_html = avatar_html.replace(
            "/*BODY_POSE__*/null",
            json.dumps(motion_queue[0].get("body_pose") if motion_queue else None,
                       ensure_ascii=False, separators=(",", ":")),
        )
        avatar_html = avatar_html.replace(
            "/*MOTION_LANGUAGE__*/\"kk-KZ\"", json.dumps(motion_language)
        )
        try:
            from src.motion_api import ensure_motion_api
            ensure_motion_api()
        except OSError as api_error:
            st.warning(f"Локальный API motion-клипов не запустился: {api_error}")
        components.html(avatar_html, height=760, scrolling=False)

