# DosYm Authentication Providers Implementation Plan

> **For agentic workers:** Implement task-by-task with test-driven development. The active user request authorizes local implementation in this session.

**Goal:** Allow the operator to select Supabase Auth or direct Google OAuth through the DosYm Python API without changing the PWA account workflow.

**Architecture:** `DOSYM_AUTH_PROVIDER` selects one server verifier. Direct Google OAuth uses a backend callback, verified Google identity, and a short-lived DosYm bearer session; Supabase keeps its existing PKCE flow. Drive credentials remain separate.

**Tech Stack:** FastAPI, existing signed-token helpers, Google Auth Python library, Next.js client component, unittest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-29-dosym-auth-providers-design.md`

## Global Constraints

- Provider values are exactly `supabase` and `google`.
- Login requests only `openid email profile`; no Google Drive scope is part of user sign-in.
- Google subject (`sub`) is the stable user identifier; email only determines configured first-moderator status.
- OAuth state expires after 10 minutes; DosYm sessions expire after 1 hour.
- Local test identities remain development-only and loopback-only.
- Drive OAuth remains a separate server-side credential set.

## Review Focus

- Invalid state, mismatched nonce, unverified email, or invalid Google audience must not create a session.
- A signed session with the wrong purpose or expired timestamp must not authenticate.
- Supabase mode must keep its current PKCE login and verifier behavior.
- Invalid environment provider and production credentials for the inactive provider must not silently activate a different provider.
- OAuth callback errors and the one-time session token must not remain in browser history after callback handling.

---

### Task 1: Provider configuration and backend Google OAuth

**Files:** Modify `backend/settings.py`, `backend/auth.py`, `backend/api.py`, `backend/store.py`, `backend/requirements.txt`, `backend/.env.example`; Test `tests/test_pwa_auth_providers.py`.

**Interfaces:** `/auth/config` returns `{auth_provider, google_configured, local_auth, storage}`. Google routes are `/auth/google/start` and `/auth/google/callback`. Direct session token claims contain only `purpose=session` and stable `user_id`.

- [ ] Add failing tests for provider validation, configured state, state/nonce validation, verified Google subject, and authenticated `/me` after callback.
- [ ] Run the new tests and confirm failure for missing provider/OAuth flow.
- [ ] Add provider settings and conditional production requirements; implement Google authorization URL, server-side code exchange, ID-token verification, account upsert, signed session, and safe frontend redirect.
- [ ] Run `python -m unittest tests.test_pwa_auth_providers tests.test_pwa_api`.

### Task 2: PWA provider-aware login and session

**Files:** Modify `pwa/lib/client.ts`, `pwa/features/auth.tsx`, `pwa/features/workspace.tsx`, `pwa/.env.example`.

**Interfaces:** `auth/config` drives login routing. Supabase mode uses existing PKCE; Google mode navigates to the Python callback and stores a token received in the callback fragment as `dosym-google-session`.

- [ ] Add a failing Playwright test with backend auth config set to Google and assert that the sign-in action targets the backend OAuth start endpoint.
- [ ] Run the targeted PWA test and confirm it fails because Supabase is currently required.
- [ ] Implement provider-aware Google sign-in, callback handling, refresh and logout while preserving the Supabase branch.
- [ ] Run `npm run typecheck`, `npm test`, and `npm run build` in `pwa/`.

### Task 3: Operations documentation and regressions

**Files:** Modify `docs/DEPLOYMENT.md`, `docs/PWA_PROGRESS.md`, `README.md`, `PROJECT_MAP.md`.

- [ ] Document both provider settings, local Google callback configuration, separate Drive OAuth credentials, and the production domain prerequisite.
- [ ] Run the complete Python suite and root JavaScript suite.
- [ ] Review `git diff` and confirm no secrets, OAuth tokens, SSH keys, or user data were added.

## Expected external prerequisites

Creating the Cloud project and enabling Drive API have been completed separately in the user's Google Cloud account. OAuth clients and Drive refresh tokens remain unconfigured until their scopes, public contact information, and redirect domains are confirmed.
