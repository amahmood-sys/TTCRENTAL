# Security Audit — TTC Subway Delay Dashboard

_Last reviewed: 2026 · Scope: entire repository at time of audit._

## Architecture context (why some "web API" items don't map)

This is a **Streamlit application**, not an HTTP/REST API. It has no user-defined
routes, no `/login` endpoint, no request/response handlers, and (as of the login
gate's removal) no authentication. The whole app is served over a single
Streamlit WebSocket session. Several common web-API hardening items therefore do
not apply literally and are addressed by their closest real analog instead.

## What was done

### 1. Rate limiting
- **Per-route rate limiting / "5 attempts per 15 min on auth routes":** Not
  applicable — there are no HTTP routes and no auth routes (the login gate was
  removed at the user's request). There is nothing to brute-force.
- **Real analog implemented:** the manual **↻ Refresh** button is the only user
  action that triggers an outbound call to the TTC feed. It is now throttled to
  **one refresh per 5 seconds** per session (`MANUAL_REFRESH_COOLDOWN`), and the
  feed itself is cached for 30 s (`@st.cache_data(ttl=30)`), so the upstream feed
  cannot be hammered.

### 2. Secret scan (hardcoded keys / tokens / passwords)
- **Working tree: clean.** No API keys, tokens, or passwords. The app needs none
  — the TTC GTFS-RT alerts feed is public and unauthenticated.
- **Finding (git history):** the previously-added demo login (`aayan` / `123456`)
  still exists in commit history (`9618ede`, removed in `6f6600a`). It is no
  longer in any live file. See "Remaining items" for remediation.

### 3. Sensitive data → environment variables
- There is **no sensitive data** in this project to externalize. The one piece of
  configuration — the feed URL — is now overridable via the `TTC_ALERTS_URL`
  environment variable, with a public default.
- `.gitignore` excludes `.streamlit/secrets.toml`, so if credentials are ever
  reintroduced they go through Streamlit secrets / env, never the repo.
- **Frontend exposure:** none. There is no client-side JS bundle and no secret is
  shipped to the browser.

### 4. Input sanitization / oversized & malformed payloads
- **User inputs** are all constrained Streamlit widgets (date picker, multiselect
  restricted to a fixed option list, bounded slider). There is no free-text input
  and no user value reaches a database, shell, `eval`, or file path, so injection
  vectors are minimal by construction.
- **The real untrusted input is the external TTC feed.** Hardened:
  - Response body is **streamed and hard-capped at 5 MB** (`MAX_FEED_BYTES`),
    with a fast reject on an oversized `Content-Length`, preventing memory
    exhaustion from a malicious/malformed response.
  - Number of alerts processed is bounded (`MAX_ALERTS = 500`).
  - All feed text is passed through `_clean_feed_text()` before rendering:
    strips control characters, neutralizes Markdown/HTML-significant characters
    (defense-in-depth on top of Streamlit's HTML escaping), and truncates to
    500 chars.
  - Protobuf parsing is wrapped in `try/except`; any failure degrades to a
    warning banner instead of crashing.
- **Dataset load** (`load_data`) now validates required columns are present and
  coerces `Hour` defensively, dropping malformed rows.

## Remaining items / recommendations

| # | Item | Severity | Recommendation |
|---|------|----------|----------------|
| 1 | Demo password `123456` remains in git history | Low (private repo, weak throwaway value, gate removed) | Don't reuse that password anywhere. If you want it fully gone, scrub history (`git filter-repo`) and force-push — happy to do this on request. |
| 2 | App is publicly viewable once deployed | Info | It only displays public open data, so this is by design. Re-add the login gate (or Streamlit Cloud's built-in viewer auth) if you want to restrict access. |
| 3 | `data/download_data.py` fetches remote XLSX at build time | Low | It's a dev-time script run manually; it hits pinned GitHub-hosted URLs over HTTPS. Consider verifying a checksum if the source repo is untrusted. |
| 4 | No Content-Security-Policy / security headers | Info | Streamlit manages its own serving; headers are typically added at the reverse proxy / host layer if needed. |

## Summary

No credentials or secrets are present in the deployable code, and there is no
sensitive data to leak. The genuine attack surface — the untrusted upstream feed
— is now size-capped, rate-limited, sanitized, and fail-safe. The only real
finding is historical (item 1), which is low severity and easily remediated.
