# DosYm authentication providers

Date: 2026-10-29. Status: approved direction from the user's request to continue local setup and retain a choice between Supabase and the VPS.

## Intent

Keep the current Supabase Google sign-in usable while adding direct Google OAuth handled by the DosYm Python API. The operator selects one provider in backend configuration; users still see one Google sign-in button.

## Goals and constraints

- `DOSYM_AUTH_PROVIDER=supabase|google` selects the backend authentication strategy.
- Supabase mode preserves its existing access-token verification and browser session.
- Google mode uses a server-side authorization-code flow, validates the Google ID token and OAuth state, then issues a short-lived DosYm-signed session.
- Google login requests only `openid email profile`; Drive storage remains a separate server credential and API scope.
- Moderator status remains server-assigned using the configured moderator email; never trust a client-supplied role.
- Local test identities remain loopback-only and disabled unless explicitly enabled.
- No secrets, SSH credentials, user videos, or cloud database credentials enter the repository.
- Local callback URLs can be used during development. Production redirect URLs and live OAuth cannot be completed until the VPS and frontend HTTPS domains are known.

## Approaches considered

1. Supabase only: smallest change, but does not meet the user's request to use their VPS directly.
2. Remove Supabase and use VPS only: direct, but loses a supported fallback the user explicitly requested.
3. Provider switch in the Python backend, with matching frontend behavior: selected because it keeps one UI and allows the operator to change providers without changing account roles or upload APIs.

## Design

FastAPI owns `/auth/google/start` and `/auth/google/callback` in Google mode. The callback checks signed, expiring state and nonce; exchanges the code server-side; validates the ID token with Google's library; upserts the Google `sub` as the stable user id; and redirects to the PWA with a short-lived session in the URL fragment. The PWA stores that token in session storage and removes the fragment immediately. API requests continue using bearer tokens. Supabase mode keeps its current PKCE callback.

The selected provider is returned from `/auth/config`. `DOSYM_GOOGLE_CLIENT_ID` and `DOSYM_GOOGLE_CLIENT_SECRET` are dedicated to user sign-in. Existing `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` remain dedicated to Drive storage.

## Non-goals

This change does not create production OAuth credentials, configure Drive refresh-token consent, deploy to Vercel, connect the VPS over SSH, or create a user-facing provider selector. The provider choice is an operator-controlled environment setting, not an end-user setting.
