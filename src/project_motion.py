"""Automatic project upload → searchable motion library workflow."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


DEFAULT_SETTINGS = {
    "enabled": True, "source": "local-project-upload", "license_name": "",
    "rights_confirmed": False, "signer_id": "", "input_mirrored": False,
}


def read_project_json(project_dir: str | Path, name: str) -> dict:
    path = Path(project_dir) / name
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Некорректный файл настроек: {path.name}")
    return value


def write_project_json(project_dir: str | Path, name: str, value: dict) -> None:
    directory = Path(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".motion-", suffix=".json", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
        os.replace(temporary, directory / name)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_settings(project_dir: str | Path) -> dict:
    return {**DEFAULT_SETTINGS, **read_project_json(project_dir, "motion_import_settings.json")}


def settings_problem(settings: dict) -> str | None:
    if not settings.get("enabled"):
        return "Автоматическая подготовка выключена."
    if not str(settings.get("license_name") or "").strip():
        return "Укажите основание использования видео в настройках автоматической подготовки."
    if settings.get("rights_confirmed") is not True:
        return "Подтвердите право использования записей этого проекта в настройках подготовки."
    return None


def prepare_project_videos(project_dir: str | Path, label: str, videos, settings: dict,
                           *, db_path=None, progress=None) -> list[dict]:
    """Import each saved video independently; unchanged inputs use the DB cache.

    Reports are durable and include failures so a later retry is possible. A
    failed clip never prevents the remaining files from being prepared.
    """
    from src.motion_db import clip_tracking_eligible, get_motion_clip, import_video_motion

    problem = settings_problem(settings)
    if problem:
        raise ValueError(problem)
    if not label.strip():
        raise ValueError("Укажите слово или фразу проекта.")
    paths = list(videos)
    report = read_project_json(project_dir, "motion_import_report.json")
    results = []
    video_dir = (Path(project_dir) / "videos").resolve()
    for index, value in enumerate(paths):
        path = Path(value).resolve()
        row = {"video": path.name, "label": label.strip(), "clip_id": None}
        try:
            if path.parent != video_dir:
                raise ValueError("Видео должно находиться в папке videos выбранного проекта.")
            clip_id = import_video_motion(
                label.strip(), path, phrase=label.strip(), language="kk-KZ",
                source=str(settings.get("source") or "local-project-upload").strip(),
                license_name=str(settings["license_name"]).strip(), rights_confirmed=True,
                signer_id=str(settings.get("signer_id") or "").strip() or None,
                input_mirrored=bool(settings.get("input_mirrored")), db_path=db_path,
            )
            clip = get_motion_clip(clip_id, db_path=db_path)
            if clip is None:
                raise RuntimeError("Сохранённый клип не удалось прочитать.")
            metadata = clip["metadata"]
            row["clip_id"] = clip_id
            row["hand_coverage"] = metadata.get("hand_detection_coverage")
            row["pose_coverage"] = metadata.get("body_pose_coverage")
            if not clip_tracking_eligible(metadata):
                row.update(status="needs_video", message="Руки видны слишком редко; снимите видео заново. Клип исключён из перевода.")
            elif float(metadata.get("body_pose_coverage") or 0) < .5:
                row.update(status="hands_only", message="Кисти доступны; для полного аватара нужно видео с видимыми плечами и локтями и установленная Pose-модель.")
            else:
                row.update(status="ready", message="Точки извлечены; доступен предварительный просмотр. Откройте аватар для подготовки и визуальной проверки движения.")
        except Exception as error:
            row.update(status="error", message=f"{type(error).__name__}: {error}")
        report[path.name] = row
        write_project_json(project_dir, "motion_import_report.json", report)
        results.append(row)
        if progress is not None:
            progress((index + 1) / len(paths), path.name)
    return results
