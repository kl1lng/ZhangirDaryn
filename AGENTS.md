# DosYm

- Read `PROJECT_MAP.md` and the PWA spec/plan before changing the public app.
- Keep the existing Streamlit/SQLite authoring tools working. Public data belongs
  in a separate database; never import a user's existing videos implicitly.
- `pwa/` is the Next.js app; `backend/` is the Python service. Video bytes bypass
  Vercel. Never expose Drive credentials, resumable URLs, or source files publicly.
- Only server roles grant moderation. Local test identities are explicitly marked,
  loopback-only, disabled by default, and forbidden in production mode.
- Source deletion must not cascade to coordinates. Only approved, usable artifacts
  are public or trainable. Validate stored arrays without pickle.
- Run root JS/Python regressions plus relevant PWA checks. Record what actually ran.
- No push, cloud resource changes, or deploy under a local-development request.
