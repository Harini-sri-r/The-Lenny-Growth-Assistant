# UI manual test plan

Run after preflight, PostgreSQL migrations, and both local servers are ready. Use the existing ChromaDB collection; do not ingest or reindex for these checks.

## Start the application

**Backend terminal (project root):**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-local.ps1
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn --app-dir backend app.main:app --reload
```

The preflight is read-only. Confirm `http://localhost:8000/health` before opening the app.

**Frontend terminal:**

```powershell
Set-Location .\frontend
npm ci
npm test
npm run build
npm run dev
```

Open the local URL Vite prints, normally `http://localhost:5173`.

## Manual checks

1. Register with a valid name/email, a 12-character password, and matching confirmation. Confirm a mismatch blocks submission, validation is readable, duplicate email handling is generic, login gives the same error for unknown email and wrong password, sign in and log out work, and HTTPS cookies are Secure/HttpOnly. Confirm state-changing requests carry the CSRF header.
2. Confirm a new persisted chat appears, refresh, and confirm history remains. Search, rename, delete, and switch conversations.
3. Create a second account. Verify it cannot list/read/delete the first account's sessions or artifacts. Return to the first account and verify its records persist.
4. Ask a question likely covered by the existing index. Inspect citations/source cards and verify `grounded: true`; open an available source URL. Ask a follow-up and verify context comes from the selected thread.
5. Ask an unrelated question. Confirm explicit insufficient evidence, `grounded: false`, and no source cards.
6. Stop Ollama and send a message. Confirm a safe error and a retry action. Retry after restarting Ollama and confirm one persisted user turn, not duplicates.
7. Generate a Markdown Ship 30 essay. Check actual length, citations, source list, and duplicate prevention. Refresh and reopen; test copy/download.
8. From an existing conversation, generate a Markdown artifact, then generate a complete HTML/CSS artifact. Confirm both use retrieved source citations and appear in the viewer beside chat. Refresh, reopen each from the saved list, and test copy/download.
9. Inspect HTML preview: it must use an empty-sandbox iframe and restrictive CSP. Confirm scripts, network connections, remote resources, nested frames, forms, and objects are blocked; app auth cookies/tokens are not exposed. Inline styling and `data:` images are allowed. Treat downloaded HTML as untrusted outside the viewer.
10. Check mobile/sidebar/artifact panels, keyboard navigation, focus, reduced motion, loading/API-down states, long tables/code, and absence of secrets/transcript passages from the UI and logs.
11. Sign out, navigate away and back with browser history, and verify the back-forward cache shows the auth loading state until `/auth/me` succeeds; revoked sessions must return to sign-in without displaying cached conversations.

## Failure handling

- If preflight reports missing packages, install `backend/requirements.txt` in the same Python environment used by Uvicorn.
- For a 503, inspect the backend terminal for the sanitized diagnostic context; do not clear/rebuild ChromaDB as a first troubleshooting step.
- PostgreSQL reachability alone does not confirm credentials/schema; migrations and API requests are separate checks.
- Health confirms process liveness only. Verify successful grounded and unsupported chat requests separately.
