# UI manual test plan

Run this after the backend preflight passes, PostgreSQL migrations are applied, and both local servers are running. Use the existing ChromaDB collection. Do not run ingestion or `--reindex` for this test plan. Use only the local licensed archive, and do not include transcript passages in screenshots or recordings.

## Start the application

Use two PowerShell terminals from the project root.

**Terminal 1: backend**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-local.ps1
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn --app-dir backend app.main:app --reload
```

The preflight is read-only. The migration command applies pending schema changes; the expected current migration is already recorded in this environment. Check `http://localhost:8000/health` before opening the UI.

**Terminal 2: frontend**

```powershell
Set-Location .\frontend
npm ci
npm test
npm run build
npm run dev
```

Open the local URL Vite prints, normally `http://localhost:5173`.

## Manual checks

1. In a clean browser profile, confirm conversations load and a new session appears. Refresh and confirm the session persists.
2. Ask a question likely covered by the existing indexed archive. Confirm the answer includes source labels and source cards, and the API response has `grounded: true`. Open an available source link. Create a second conversation, verify it is independent, then return to the first.
3. Ask an unrelated question. Confirm the assistant gives the insufficient-evidence response, `grounded: false`, and no source cards.
4. Stop Ollama and send a message. Confirm the UI shows a safe service error, backend logs contain a diagnostic stack, and the user message/session remain. Restart Ollama and confirm a request succeeds.
5. Generate a Markdown Ship 30 for 30 essay for a specific topic and audience. Confirm its actual word count and source list appear in the Artifact Viewer. Refresh and confirm the artifact remains.
6. Generate an HTML essay. Confirm the preview displays inside an iframe. Inspect it in browser developer tools: the iframe has an empty `sandbox`, includes restrictive CSP, and runs no scripts or remote resources.
7. Check narrow-screen behavior, loading state, API-down error, blank topic validation, keyboard submission, and that no credentials or transcript body appear in browser UI or logs.

## Failure handling

- If preflight reports missing packages, install them with `python -m pip install -r backend/requirements.txt` in the same Python environment used to run Uvicorn.
- If the chat endpoint returns 503, inspect the backend terminal for the server-side exception. Do not clear or re-index ChromaDB as the first troubleshooting step.
- PostgreSQL TCP reachability from preflight does not validate credentials, database existence, schema, or application startup; migrations and the health endpoint cover separate steps.
- An API health response verifies process liveness only. Successful supported and unsupported chat turns are required to verify RAG behavior.
