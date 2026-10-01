"""Проверка и пакетный импорт размеченных видеожестов из CSV-манифеста.

Модуль ничего не скачивает. По умолчанию CLI проверяет манифест и пути;
запись в SQLite выполняется только с явным флагом --apply.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
REQUIRED_COLUMNS = {"video_path", "phrase", "source", "license", "rights_confirmed"}
TRUE_VALUES = {"1", "true", "yes", "y", "да", "подтверждаю"}


@dataclass(frozen=True)
class ManifestRow:
    line: int
    video_path: Path
    phrase: str
    source: str
    license_name: str
    signer_id: str | None
    language: str
    aliases: tuple[str, ...] = ()
    input_mirrored: bool = False
    start_seconds: float = 0.0
    end_seconds: float | None = None
    translations: tuple[tuple[str, str], ...] = ()
    rights_confirmed: bool = False


def read_manifest(path: str | Path, *, check_files: bool = True) -> tuple[list[ManifestRow], list[str]]:
    """Читает CSV UTF-8/UTF-8-SIG и проверяет метки, основания и локальные файлы."""
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        return [], [f"Манифест не найден: {manifest_path}"]

    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
            return _read_manifest_stream(stream, manifest_path, check_files=check_files)
    except (OSError, UnicodeError, csv.Error) as error:
        return [], [f"Не удалось прочитать CSV: {error}"]


def read_manifest_text(
    text: str,
    *,
    base_dir: str | Path,
    check_files: bool = True,
) -> tuple[list[ManifestRow], list[str]]:
    """Валидирует загруженный CSV, считая относительные пути от base_dir."""
    manifest_path = Path(base_dir).expanduser().resolve() / "uploaded_manifest.csv"
    return _read_manifest_stream(
        io.StringIO(text), manifest_path, check_files=check_files, allowed_root=manifest_path.parent
    )


def save_uploaded_videos(
    uploaded_files,
    video_dir: str | Path,
) -> tuple[list[Path], list[str]]:
    """Сохраняет выбранные пользователем видео без перезаписи существующих файлов."""
    target_dir = Path(video_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    errors: list[str] = []

    for uploaded in uploaded_files or ():
        name = str(getattr(uploaded, "name", ""))
        candidate = Path(name)
        if (not name or candidate.name != name or name in {".", ".."}
                or candidate.suffix.lower() not in VIDEO_EXTENSIONS):
            errors.append(f"Недопустимое имя/формат видео: {name or '(пустое имя)'}")
            continue
        destination = (target_dir / name).resolve()
        if destination.parent != target_dir:
            errors.append(f"Путь видео выходит за папку проекта: {name}")
            continue
        try:
            data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else bytes(uploaded)
            if not data:
                errors.append(f"Пустой файл: {name}")
                continue

            digest = hashlib.sha256(data).digest()
            if destination.exists():
                existing_hash = hashlib.sha256()
                with destination.open("rb") as existing_file:
                    for chunk in iter(lambda: existing_file.read(1024 * 1024), b""):
                        existing_hash.update(chunk)
                if existing_hash.digest() == digest:
                    saved.append(destination)
                else:
                    errors.append(f"Файл уже существует и отличается; не перезаписан: {name}")
                continue

            # Exclusive creation prevents clobbering a file that appeared after
            # the existence check. Remove a partial file if the write fails.
            try:
                with destination.open("xb") as output:
                    output.write(data)
            except FileExistsError:
                errors.append(f"Файл уже появился в папке; не перезаписан: {name}")
                continue
            except OSError:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            saved.append(destination)
        except Exception as error:
            errors.append(f"Не удалось сохранить {name}: {type(error).__name__}: {error}")

    return saved, errors


def _read_manifest_stream(
    stream,
    manifest_path: Path,
    *,
    check_files: bool,
    allowed_root: Path | None = None,
) -> tuple[list[ManifestRow], list[str]]:

    rows: list[ManifestRow] = []
    errors: list[str] = []
    try:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or ())
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            return [], ["Нет обязательных колонок: " + ", ".join(sorted(missing_columns))]

        for line, record in enumerate(reader, start=2):
            if not record or not any((value or "").strip() for value in record.values()):
                continue
            label = (record.get("phrase") or "").strip()
            source = (record.get("source") or "").strip()
            license_name = (record.get("license") or "").strip()
            confirmed = (record.get("rights_confirmed") or "").strip().lower()
            mirrored_value = (record.get("input_mirrored") or "").strip().lower()
            start_text = (record.get("start_seconds") or "").strip()
            end_text = (record.get("end_seconds") or "").strip()
            translations_text = (record.get("translations") or "").strip()
            raw_path = (record.get("video_path") or "").strip()
            row_errors = []
            if not label:
                row_errors.append("пустая phrase")
            if not source:
                row_errors.append("пустой source")
            if not license_name:
                row_errors.append("не указана license/основание")
            if confirmed not in TRUE_VALUES:
                row_errors.append("rights_confirmed не подтверждён")
            if mirrored_value and mirrored_value not in TRUE_VALUES | {"0", "false", "no", "n", "нет"}:
                row_errors.append("input_mirrored должен быть true/false или да/нет")
            try:
                start_seconds = float(start_text) if start_text else 0.0
                if not math.isfinite(start_seconds) or start_seconds < 0:
                    raise ValueError
            except ValueError:
                start_seconds = 0.0
                row_errors.append("start_seconds должен быть конечным неотрицательным числом")
            try:
                end_seconds = float(end_text) if end_text else None
                if end_seconds is not None and (not math.isfinite(end_seconds) or end_seconds <= start_seconds):
                    raise ValueError
            except ValueError:
                end_seconds = None
                row_errors.append("end_seconds должен быть конечным числом больше start_seconds")
            video_path = Path(raw_path).expanduser()
            if not video_path.is_absolute():
                video_path = manifest_path.parent / video_path
            video_path = video_path.resolve()
            if allowed_root is not None:
                try:
                    video_path.relative_to(allowed_root)
                except ValueError:
                    row_errors.append("путь видео выходит за папку проекта")
            if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
                row_errors.append("неподдерживаемый формат видео")
            if check_files and not video_path.is_file():
                row_errors.append(f"файл не найден: {video_path}")
            if row_errors:
                errors.append(f"Строка {line}: " + "; ".join(row_errors))
                continue
            translations: list[tuple[str, str]] = []
            for item in translations_text.replace(";", "|").split("|"):
                item = item.strip()
                if not item:
                    continue
                if "=" not in item:
                    row_errors.append(
                        f"перевод «{item}» должен иметь формат language=текст"
                    )
                    continue
                translation_language, translation_text = (part.strip() for part in item.split("=", 1))
                if (not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", translation_language)
                        or not translation_text):
                    row_errors.append(
                        f"перевод «{item}» должен иметь язык и непустой текст"
                    )
                    continue
                translations.append((translation_language, translation_text))
            if row_errors:
                errors.append(f"Строка {line}: " + "; ".join(row_errors))
                continue
            rows.append(ManifestRow(
                line=line,
                video_path=video_path,
                phrase=label,
                source=source,
                license_name=license_name,
                signer_id=(record.get("signer_id") or "").strip() or None,
                language=(record.get("language") or "kk-KZ").strip() or "kk-KZ",
                aliases=tuple(
                    alias.strip()
                    for alias in (record.get("aliases") or "").replace("|", ";").split(";")
                    if alias.strip()
                ),
                translations=tuple(translations),
                input_mirrored=mirrored_value in TRUE_VALUES,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                rights_confirmed=confirmed in TRUE_VALUES,
            ))
    except csv.Error as error:
        return [], [f"Не удалось прочитать CSV: {error}"]

    if not rows and not errors:
        errors.append("В CSV нет строк для импорта")
    return rows, errors


def import_manifest(
    rows: list[ManifestRow],
    importer: Callable[..., int] | None = None,
    progress: Callable[[int, int, ManifestRow], None] | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[tuple[ManifestRow, int]], list[tuple[ManifestRow, str]]]:
    """Импортирует каждую запись отдельно и возвращает успехи и ошибки."""
    use_default_importer = importer is None
    if importer is None:
        from src.motion_db import import_video_motion
        importer = import_video_motion

    imported: list[tuple[ManifestRow, int]] = []
    failures: list[tuple[ManifestRow, str]] = []
    alias_errors = _preflight_alias_conflicts(rows, db_path=db_path)
    alias_errors.update(_preflight_phrase_conflicts(rows, db_path=db_path))
    extraction_cache: dict = {}
    processing_rows = list(rows)
    remaining_by_video: dict[str, int] = {}
    if use_default_importer:
        def video_key(row: ManifestRow) -> str:
            return str(row.video_path.expanduser().resolve()).casefold()

        for row in rows:
            key = video_key(row)
            remaining_by_video[key] = remaining_by_video.get(key, 0) + 1
        # Keep one source's intervals together so its MediaPipe tracks can be
        # extracted once, while preserving the manifest's output order below.
        processing_rows.sort(key=lambda row: (video_key(row), row.line))

    for index, row in enumerate(processing_rows, start=1):
        try:
            if row.line in alias_errors:
                raise ValueError(alias_errors[row.line])
            # Construct explicit arguments separately to keep custom importer
            # callbacks backwards-compatible with the original signature.
            options = {
                "phrase": row.phrase,
                "language": row.language,
                "source": row.source,
                "license_name": row.license_name,
                "signer_id": row.signer_id,
                "input_mirrored": row.input_mirrored,
            }
            if row.start_seconds != 0.0 or row.end_seconds is not None:
                options.update({
                    "start_seconds": row.start_seconds,
                    "end_seconds": row.end_seconds,
                })
            if use_default_importer and db_path is not None:
                options["db_path"] = db_path
            if use_default_importer:
                options["extraction_cache"] = extraction_cache
                options["rights_confirmed"] = row.rights_confirmed
            clip_id = importer(row.phrase, row.video_path, **options)
            if row.aliases or row.translations:
                from src.motion_db import register_gesture, register_gesture_aliases
                gesture_id = register_gesture(
                    row.phrase,
                    row.phrase,
                    language=row.language,
                    source=row.source,
                    license_name=row.license_name,
                    **({"db_path": db_path} if db_path is not None else {}),
                )
                alias_groups: dict[str, list[str]] = {}
                if row.aliases:
                    alias_groups.setdefault(row.language, []).extend(row.aliases)
                for translation_language, translation in row.translations:
                    alias_groups.setdefault(translation_language, []).append(translation)
                for alias_language, aliases in alias_groups.items():
                    register_gesture_aliases(
                        gesture_id, aliases, language=alias_language,
                        **({"db_path": db_path} if db_path is not None else {}),
                    )
            imported.append((row, int(clip_id)))
        except Exception as error:  # report one bad video; continue the batch
            failures.append((row, f"{type(error).__name__}: {error}"))
        if progress is not None:
            progress(index, len(rows), row)
        if use_default_importer:
            key = video_key(row)
            remaining_by_video[key] -= 1
            if remaining_by_video[key] == 0:
                extraction_cache.pop(str(row.video_path.expanduser().resolve()), None)
    imported.sort(key=lambda entry: entry[0].line)
    failures.sort(key=lambda entry: entry[0].line)
    return imported, failures


def _preflight_alias_conflicts(
    rows: list[ManifestRow], *, db_path: str | Path | None = None
) -> dict[int, str]:
    """Reject known alias/label collisions before any video is processed."""
    if not any(row.aliases or row.translations for row in rows):
        return {}
    from src.motion_db import connect, normalize_text

    def key(text: str) -> str:
        return " ".join(normalize_text(text))

    with connect(db_path) as db:
        labels = db.execute(
            "SELECT id, lemma, phrase, language FROM gestures"
        ).fetchall()
        aliases = db.execute(
            "SELECT normalized, gesture_id, language FROM gesture_aliases"
        ).fetchall()

    label_owners: dict[tuple[str, str], int | tuple[str, str, str]] = {}
    exact_gestures: dict[tuple[str, str, str], int] = {}
    for gesture_id, lemma, phrase, language in labels:
        if phrase is not None:
            exact_gestures[(language, lemma, phrase)] = int(gesture_id)
        for label in (lemma, phrase):
            normalized = key(label or "")
            if normalized:
                label_owners.setdefault((language, normalized), int(gesture_id))

    alias_owners = {(language, normalized): int(gesture_id)
                    for normalized, gesture_id, language in aliases}
    owners: dict[int, int | tuple[str, str, str]] = {}
    batch_labels: dict[tuple[str, str], int | tuple[str, str, str]] = {}
    conflicts: dict[int, str] = {}
    for row in rows:
        normalized_phrase = key(row.phrase)
        owner = exact_gestures.get(
            (row.language, row.phrase.strip().lower(), row.phrase),
            ("manifest", row.language, normalized_phrase),
        )
        owners[row.line] = owner
        label_key = (row.language, normalized_phrase)
        batch_labels.setdefault(label_key, owner)

    assigned_aliases: dict[tuple[str, str], int | tuple[str, str, str]] = {}
    for row in rows:
        owner = owners[row.line]
        all_aliases = [(row.language, alias) for alias in row.aliases]
        all_aliases.extend(row.translations)
        for alias_language, display_alias in all_aliases:
            normalized = key(display_alias)
            if not normalized:
                conflicts[row.line] = f"Вариант «{display_alias}» пуст или не содержит букв/цифр"
                break
            lookup = (alias_language, normalized)
            existing_label_owner = label_owners.get(lookup)
            batch_label_owner = batch_labels.get(lookup)
            existing_alias_owner = alias_owners.get(lookup)
            assigned_owner = assigned_aliases.get(lookup)
            other_owner = next((candidate for candidate in (
                existing_label_owner, batch_label_owner, existing_alias_owner, assigned_owner
            ) if candidate is not None and candidate != owner), None)
            if other_owner is not None:
                conflicts[row.line] = (
                    f"Вариант «{display_alias}» уже относится к другому жесту "
                    "(конфликт меток/алиасов в базе или этом CSV)"
                )
                break
            assigned_aliases[lookup] = owner
    return conflicts


def _preflight_phrase_conflicts(
    rows: list[ManifestRow], *, db_path: str | Path | None = None
) -> dict[int, str]:
    """Reject canonically identical phrases assigned to different lemmas."""
    from src.motion_db import connect, normalize_text

    def key(text: str) -> str:
        return " ".join(normalize_text(text))

    with connect(db_path) as db:
        existing = db.execute(
            "SELECT language, lemma, phrase FROM gestures WHERE phrase IS NOT NULL"
        ).fetchall()

    existing_lemmas: dict[tuple[str, str], set[str]] = {}
    for language, lemma, phrase in existing:
        phrase_key = key(phrase or "")
        if phrase_key:
            existing_lemmas.setdefault((language, phrase_key), set()).add(key(lemma))

    batch: dict[tuple[str, str], list[ManifestRow]] = {}
    for row in rows:
        phrase_key = key(row.phrase)
        if phrase_key:
            batch.setdefault((row.language, phrase_key), []).append(row)

    conflicts: dict[int, str] = {}
    for (language, phrase_key), phrase_rows in batch.items():
        lemmas = existing_lemmas.get((language, phrase_key), set())
        lemmas.update(key(row.phrase) for row in phrase_rows)
        if len(lemmas) <= 1:
            continue
        for row in phrase_rows:
            conflicts[row.line] = (
                f"Фраза «{row.phrase}» совпадает после нормализации, "
                "но связана с разными леммами; уточните разметку до импорта"
            )
    return conflicts


def select_manifest_batch(
    rows: list[ManifestRow], *, offset: int = 0, limit: int | None = None
) -> list[ManifestRow]:
    """Select a deterministic slice of validated rows for resumable large imports."""
    if offset < 0:
        raise ValueError("offset должен быть неотрицательным")
    if limit is not None and limit < 1:
        raise ValueError("limit должен быть положительным")
    return rows[offset:] if limit is None else rows[offset:offset + limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверить/импортировать motion-клипы из CSV")
    parser.add_argument("manifest", type=Path, nargs="?",
                        help="CSV с колонками video_path, phrase, source, license, rights_confirmed")
    parser.add_argument("--apply", action="store_true", help="Записать валидные клипы в SQLite")
    parser.add_argument("--offset", type=int, default=0,
                        help="Начать с offset-й корректной строки данных (нумерация с нуля)")
    parser.add_argument("--limit", type=int,
                        help="Импортировать не более N корректных строк в этом запуске")
    parser.add_argument("--coverage", action="store_true",
                        help="Показать покрытие текущей motion-базы и завершить без импорта")
    parser.add_argument("--db", type=Path,
                        help="Путь к SQLite motion-библиотеке (по умолчанию путь проекта)")
    args = parser.parse_args()

    if args.coverage:
        import json
        import config
        from src.motion_db import library_coverage, library_stats
        database_path = args.db or config.MOTION_DB_PATH
        payload = {
            "database": str(Path(database_path).expanduser().resolve()),
            "totals": library_stats(database_path),
            "languages": library_coverage(database_path),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.manifest is None:
        parser.error("manifest обязателен, кроме режима --coverage")

    if args.offset < 0:
        parser.error("--offset должен быть неотрицательным")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit должен быть положительным")

    rows, errors = read_manifest(args.manifest)
    for error in errors:
        print(f"ОШИБКА: {error}")
    if not rows:
        return 2
    total_rows = len(rows)
    rows = select_manifest_batch(rows, offset=args.offset, limit=args.limit)
    if not rows:
        print(f"Порция пуста: в манифесте {total_rows} корректных строк, offset={args.offset}.")
        return 2
    print(f"Корректных видео: {total_rows}; выбрано в порцию: {len(rows)} (offset={args.offset}).")
    if not args.apply:
        print("Только проверка; motion-база не изменена. Для импорта повторите команду с --apply.")
        return 1 if errors else 0

    report_every = max(1, len(rows) // 100)

    def report_progress(completed: int, total: int, row: ManifestRow) -> None:
        if completed == 1 or completed == total or completed % report_every == 0:
            print(f"Прогресс {completed}/{total} · {row.video_path.name}", flush=True)

    imported, failures = import_manifest(rows, progress=report_progress, db_path=args.db)
    for row, clip_id in imported:
        print(f"OK · строка {row.line} · {row.phrase} · clip_id={clip_id}")
    for row, error in failures:
        print(f"ОШИБКА · строка {row.line} · {row.video_path.name} · {error}")
    return 1 if errors or failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
