# DosYm: карта проекта

Переводчик казахского жестового языка: сбор и обучение распознавания,
motion-библиотека и воспроизведение записанных жестов на 3D-аватаре.
Подробности запуска и требования к моделям — в README.md.

PWA-прогресс: `docs/PWA_PROGRESS.md`. Спецификация и план: `docs/superpowers/specs/2026-10-28-dosym-pwa-design.md`, `docs/superpowers/plans/2026-10-28-dosym-pwa.md`.

## Реализовано

- `app.py` — интерфейс Streamlit, проекты, загрузка видео и обучение.
- `src/extract_landmarks.py`, `src/normalize.py` — извлечение и нормализация точек.
- `src/training_data.py`, `src/training_utils.py`, `src/train.py`,
  `src/model.py`, `src/predict.py` — данные, обучение и распознавание.
- `src/motion_db.py`, `src/motion_matcher.py`, `src/motion_api.py` —
  хранение клипов, поиск по тексту и HTTP API.
- `src/project_motion.py`, `src/ingest_manifest.py` — импорт видео в motion-базу.
- `web/index.html` — текстовый и голосовой интерфейс проигрывания.
- `web/avatar.html` — Three.js, калибровка клипов, фильтрация, IK рук,
  перенос пальцев, ограничения запястий и приближённая защита корпуса;
  панель подготовки, правок диапазонов кадров и отметки просмотра.
- `web/rig-motion.mjs` — подготовленные дорожки локальных поворотов костей,
  детерминированная перемотка, обработка пропусков, ограничение скачков,
  поправки и IndexedDB с резервным хранением в памяти вкладки.
- `web/render-scheduler.mjs` — отложенное расписание отрисовки Three.js без
  постоянного RAF в покое; `pwa/features/player.tsx` лениво монтирует iframe
  и останавливает сцену вне viewport.
- `web/models/` — модели аватара и сведения об их лицензиях.
- `tests/avatar_kinematics.test.js`, `tests/avatar_playback.test.js` —
  геометрия настоящего скелета Rocketbox и поведение проигрывателя.
- `tests/prepared_motion.test.js` — дорожки костей, кэш, пропуски,
  перемотка и диапазоны правок.
- `tests/test_*.py` — Python-проверки API, импорта и обучения.
- `backend/` — FastAPI сервис PWA: SQLite/PostgreSQL, выбор Supabase/direct Google OAuth, роли, загрузки, модерация, Drive/local source storage, extraction worker и trainer-кандидат.
- `backend/import_motion.py` — read-only dry-run и явный перенос одного или пакета готовых motion-клипов из исходной SQLite в PWA; пакет фильтруется по подтверждённым правам и качеству. Инструкция `docs/IMPORT_MOTION.md`.
- `db/migrations/001_public_pwa.sql` — закрытые PostgreSQL-таблицы PWA и RLS/revoke для browser roles.
- `pwa/` — адаптивный Next.js frontend, Google/Supabase auth integration, dictionary/avatar, upload/moderation, manifest/service worker и Playwright tests.
- `pwa/scripts/profile-performance.mjs` — локальный Edge-профиль LCP,
  long tasks, загрузки ресурсов, подготовки клипа и idle/pause RAF.
- `docs/superpowers/plans/2026-10-29-dosym-performance.md` — план
  оптимизации, статус выполненных этапов и дальнейшие измерения.
- `pwa/features/locale.tsx`, `pwa/lib/messages.json`, `pwa/lib/i18n.ts` — казахский интерфейс по умолчанию, русский/английский и сохранение выбора; офлайн-словарь генерируется `pwa/scripts/prepare-locales.mjs`.
- `pwa/lib/gesture-search.ts` — общее сопоставление кириллицы/латиницы для текущих и будущих меток; правила и источники — `docs/LOCALES_AND_SEARCH.md`.
- `scripts/start-pwa.ps1`, `scripts/stop-pwa.ps1` — управление локальными PWA процессами на loopback.
- `docs/DEPLOYMENT.md`, `docs/DATA_RETENTION.md`, `docs/PWA_TECH_SPIKE.md`, `docs/PWA_ACCEPTANCE.md` — архитектура, хранение, подготовка облака и приёмка.

## Полезные локальные команды

- `streamlit run app.py` — интерфейс приложения.
- `npm test` — JavaScript-проверки (нужны установленные зависимости).
- `python -m unittest discover -s tests` — Python-проверки.
- `./scripts/start-pwa.ps1 -WithTraining` — PWA + API + тренер после настройки окружений; инструкции: `pwa/README.md`.
- `./scripts/stop-pwa.ps1` — остановить процессы из PWA launch registry.
- `Push-Location pwa; npm run typecheck; npm test; npm run build; Pop-Location` — проверки PWA.
- `Push-Location pwa; npm run profile:performance; Pop-Location` — локальный
  лабораторный профиль PWA и проигрывания `salem` (требуются запущенные API и PWA).
- `.venv-pwa/Scripts/python.exe -m unittest discover -s tests` — Python-проверки PWA в Windows.

## Ограничения и дальнейшая работа

### Реализовано локально; облачные шаги ещё предстоят

- `docs/superpowers/specs/2026-10-28-dosym-pwa-design.md` — предлагаемые
  сценарии, экраны для ПК/телефона, Google-вход, Drive, модерация и архитектура.
- `docs/superpowers/plans/2026-10-28-dosym-pwa.md` — этапы реализации и приёмки.
- PWA, локальный API/SQLite, demo roles, загрузка, модерация, извлечение motion,
  хранение координат независимо от видео, отзыв материала, кандидат обучения,
  словарь, адаптивные экраны и offline-оболочка реализованы. Запуск и
  ограничения — в `pwa/README.md` и `docs/PWA_PROGRESS.md`.
- Google OAuth web client создан; локальный browser sign-in проверен, назначилась серверная роль модератора.
  PWA размещена на Vercel (`dosym-seven.vercel.app`), параметры Supabase и callback настроены.
  `pwa/app/api/[...path]/route.ts` поддерживает проверку Supabase-сессии без ML backend,
  только с ролью участника; `pwa/tests/hosted-auth.test.ts` проверяет эту границу доступа.
  Сквозной облачный OAuth, Drive storage, размещение Python backend, backup,
  device install QA и публикация/rollback модели ещё требуют завершения и проверки.
- Пользовательский Streamlit остаётся инструментом автора.

Полной проверки столкновений кистей, пальцев и предплечий с телом нет.
Защита запястья использует приближённую переднюю поверхность корпуса.
Нужна визуальная проверка сложных жестов и их понятности носителями КЖЯ;
геометрические тесты не заменяют такую оценку.
Автоматическая подготовка и пользовательский просмотр — разные состояния;
отметка просмотра не означает подтверждения правильности жеста носителем КЖЯ.
Поправки сохраняются в браузере, отдельно для адреса приложения; в SQLite
исходные точки не перезаписываются. Для переноса/архива доступен JSON-экспорт.
