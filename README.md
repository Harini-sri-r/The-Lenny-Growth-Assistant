# Lenny Growth Assistant

A starter foundation for a conversational assistant grounded in Lenny's Podcast and Newsletter archive.

## Current status

Implemented: FastAPI chat/session APIs, PostgreSQL models and Alembic initial migration, ChromaDB/Ollama transcript RAG, Ollama/OpenAI/Gemini provider selection, optional Claude Agent SDK research agent, grounded Ship 30 for 30 essay generation, persisted Markdown/HTML artifacts, isolated HTML preview, structured JSON request logs, and a React/Vite chat and Artifact Viewer UI.

The local Ollama path uses `llama3:latest` and `nomic-embed-text`. Browser-scoped workspace IDs are demo isolation, not authentication. Live PostgreSQL, ChromaDB, Ollama, Claude Agent SDK authentication, and browser preview security must still be checked on the demo machine.

## Existing dataset

The existing dataset remains in `lennys-newsletterpodcastdata-main/`. It contains 50 podcast Markdown files, 10 newsletter Markdown files, `index.json`, and `LICENSE.md` (63 files total, approximately 5.0 MB). The index provides title, date, word count, URL, and podcast guest/description or newsletter subtitle metadata. No transcript content was moved or copied.

The included starter archive permits personal, non-commercial use. Raw dataset redistribution and commercial use of its raw contents are prohibited by its license. Review `lennys-newsletterpodcastdata-main/LICENSE.md` before sharing or deploying.

## Local setup

1. Create and activate a Python environment: `python -m venv .venv` then `.venv\\Scripts\\Activate.ps1` (PowerShell) or `source .venv/bin/activate` (macOS/Linux).
2. Install backend dependencies: `python -m pip install -r backend/requirements.txt`.
3. Copy `.env.example` to `.env` and edit only local settings. `TRANSCRIPTS_PATH` points at the existing licensed dataset; do not copy it elsewhere.
4. Start PostgreSQL and Ollama. Pull the demo models with `ollama pull llama3:latest` and `ollama pull nomic-embed-text`.
5. Apply migrations from the repository root: `alembic -c backend/alembic.ini upgrade head`.
6. Start the API from the root: `python -m uvicorn --app-dir backend app.main:app --reload`. Health checks: `http://localhost:8000/health` and `/api/v1/health`.
7. In another terminal run `cd frontend`, `npm ci`, then `npm run dev`; open the URL Vite prints (normally `http://localhost:5173`).

### Windows PowerShell startup

Open two PowerShell terminals at the project root. In Terminal 1, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-local.ps1`, then `python -m alembic -c backend/alembic.ini upgrade head`, then `python -m uvicorn --app-dir backend app.main:app --reload`. The preflight checks Python packages (including ChromaDB), configured Ollama model tags, and PostgreSQL TCP reachability. It does not print secrets, migrate, or access the Chroma index. In Terminal 2, run `Set-Location .\frontend`, `npm ci`, `npm test`, `npm run build`, and `npm run dev`. Open the URL Vite prints. If your PowerShell execution policy permits local scripts, `.\scripts\check-local.ps1` runs the preflight directly; the documented process-scoped bypass does not change the saved machine policy.

## Configuration

`.env.example` lists supported settings. The local demo requires `DATABASE_URL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `LLM_PROVIDER=ollama`, and `AGENT_FRAMEWORK=rag_service`. Defaults target the Ollama tags `llama3:latest` and `nomic-embed-text`. `TRANSCRIPTS_PATH` and `CHROMA_PERSIST_DIRECTORY` select the dataset and index. Retrieval controls are `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_BATCH_SIZE`, `RETRIEVAL_TOP_K`, and `RETRIEVAL_MIN_SIMILARITY`. `LLM_TIMEOUT_SECONDS` controls regular provider requests; Ship 30 uses `SHIP30_GENERATION_TIMEOUT_SECONDS`, `SHIP30_MAX_OUTPUT_TOKENS`, `SHIP30_MINIMUM_RESPONSE_WORDS`, and a bounded `SHIP30_MAX_CONTINUATIONS` setting (default 3; at most four generation calls total). Per-attempt Ship 30 diagnostics include safe provider/model, timing, raw and citation-validated word counts, token usage, finish reason, and truncation status without prompts, essay content, or credentials.

`backend/requirements.txt` declares ChromaDB (`chromadb>=0.6.3,<2`) and the other backend packages. If `python -m pip show chromadb` reports it missing, install all declared dependencies from the project root with `python -m pip install -r backend/requirements.txt` (or `python -m pip install "chromadb>=0.6.3,<2"` to install only ChromaDB into the active environment). Then verify with `python -m pip check` and `python -m pip show chromadb`. Use the same Python environment for Uvicorn, ingestion, and migrations.

The default is local-only: `AGENT_FRAMEWORK=rag_service` and `LLM_PROVIDER=ollama` run chat and Ship 30 generation without cloud credentials. Pull both configured local models with Ollama: `OLLAMA_MODEL` for generation and `OLLAMA_EMBEDDING_MODEL` for retrieval. Cloud providers are optional. For Gemini, set `LLM_PROVIDER=gemini`, `GEMINI_MODEL` (default `gemini-3.5-flash`), and a valid `GEMINI_API_KEY`, then restart the backend. Ship 30 uses exactly the selected configured provider and does not silently fall back to another model; regular chat retains the existing cloud-to-Ollama fallback. For OpenAI Ship 30, set `LLM_PROVIDER=openai`, `OPENAI_MODEL`, and `OPENAI_API_KEY`. Install the official Python SDK through `python -m pip install -r backend/requirements.txt`. For Claude Agent SDK chat and Ship 30, set `AGENT_FRAMEWORK=claude_agent_sdk`, `CLAUDE_AGENT_MODEL`, `CLAUDE_AGENT_MAX_TURNS`, and a valid `ANTHROPIC_API_KEY`. Live cloud integration requires valid credentials, project access, and available quota; mocked tests do not establish live connectivity. Never put credentials in source code or commit `.env`.

Pi Coding Agent integration for this Python backend uses Pi's documented JSON event stream and supports Gemini through `GEMINI_API_KEY` and an OpenAI-compatible Ollama endpoint. Install Pi with `npm install --global @earendil-works/pi-coding-agent`, set `AGENT_FRAMEWORK=pi_coding_agent`, then choose `LLM_PROVIDER=ollama` or `gemini`. Pi receives pre-retrieved labeled passages; backend citation checks still apply. For Ollama, configure `~/.pi/agent/models.json` with base URL `http://localhost:11434/v1`, API `openai-completions`, and a model ID matching `OLLAMA_MODEL`; set the model `maxTokens` high enough for the requested output (at least 2,500 for Ship 30). When Pi returns a cited essay below the minimum, the adapter asks for up to three cited continuations within the overall timeout budget. Pi tools and session persistence are disabled, and Ollama calls run offline with stdin closed. `PI_COMMAND` selects the CLI executable; chat uses `PI_TIMEOUT_SECONDS`, and Pi essays use the separate `PI_SHIP30_TIMEOUT_SECONDS` (900 seconds by default) because local CPU models need more time to write a full essay. Timeout logs identify Pi explicitly.
Run `python scripts/inspect_dataset.py` for a metadata inventory that does not print transcript bodies. Validate Markdown and estimate chunks without external services using `python scripts/ingest_transcripts.py --validate-only`. **Do not re-index an already populated ChromaDB collection just to start the app or perform the manual UI test plan.** The normal indexing command is incremental and reuses compatible records, but updates or embeds missing chunks. Stale cleanup happens only after successful indexing. `--reindex` clears the configured collection and is only for intentional rebuilds. Override the input with `--path` or `TRANSCRIPTS_PATH`.

The RAG service returns an explicit insufficient-evidence result with no sources when retrieval finds no relevant passages. For matched passages it asks the selected LLM to answer only from context with `[S1]`-style source labels and returns matching source metadata. Ship 30 targets approximately 1,250 words and may request up to three evidence-grounded continuations, each told the remaining validated word count. It validates the merged output against the configured minimum and retrieved source IDs before any artifact is saved. In `rag_service`, `LLM_PROVIDER=gemini` selects the official Google Gen AI Python SDK adapter for chat and Ship 30; the Gemini model and credential come from `GEMINI_MODEL` and `GEMINI_API_KEY`. The model list and access can change; check Google's [Gemini API models](https://ai.google.dev/gemini-api/docs/models) for current identifiers and availability. `AGENT_FRAMEWORK=claude_agent_sdk` instead opts into Claude Agent SDK for chat and Ship 30; its in-process MCP `search_transcripts` tool queries the configured Chroma collection using Ollama embeddings. Provide valid credentials for live cloud use. Invalid framework configuration and unavailable local services still produce a safe service error. The Ship 30 skill lives in `backend/app/skills/ship30_for_30/SKILL.md`.

To send one intentional Gemini smoke request after setting `GEMINI_API_KEY` and `GEMINI_MODEL` in the local `.env`, run this from the project root in PowerShell. It invokes the adapter directly once and prints only the generated response; it is a live API call and may use account quota:

```powershell
python -c "import sys; sys.path.insert(0, 'backend'); from app.core.config import get_settings; from app.agents.providers import GeminiProvider; s = get_settings(); print(GeminiProvider(s.gemini_api_key, s.gemini_model, s.llm_timeout_seconds).generate('Reply with one short sentence.', 'Say: Gemini API smoke test succeeded.'))"
```

Generate an essay from the UI or call `POST /api/v1/artifacts/ship30` with `user_id`, `session_id`, `topic`, `audience`, and `artifact_format` (`markdown` or `html`). Artifacts are saved per browser workspace and expose the actual generated word count and transcript references. Markdown artifacts render headings, emphasis, lists, links, code, blockquotes, and citations in the Artifact Viewer; raw HTML remains inert text. HTML previews run in a sandboxed iframe with restrictive CSP; do not weaken those restrictions.

The UI stores a random workspace ID in browser local storage and uses it to scope independent sessions. This is session separation for the local demo, not authentication; do not expose the API publicly without adding real user authentication and authorization. Apply Alembic migrations before starting the API.

## Docker

Copy `.env.example` to `.env`, then run `docker compose up --build`. PostgreSQL health is checked before backend startup; the backend applies Alembic migrations before serving and exposes an HTTP health check. The licensed archive is mounted read-only and excluded from the Docker build context. ChromaDB persists in a named Docker volume. Once Ollama is running on the host and the required embedding model is pulled, run `docker compose exec backend python scripts/ingest_transcripts.py` only if the volume is not already indexed. Ollama must be reachable from the backend container (`host.docker.internal:11434` is configured for Docker). The browser calls the API on `http://localhost:8000` by default; set `VITE_API_BASE_URL` at frontend build time if the API uses another address.

## Tests

From the root run `python -m pytest backend/tests -q`. Frontend checks from `frontend/`: `npm test` and `npm run build` (the build also performs TypeScript checking). RAG automated tests use synthetic Markdown and in-memory vector storage; chat API tests use temporary SQLite and stub services. These do not establish live ChromaDB, Ollama, Claude/cloud provider, Docker or browser security behavior. For manual browser QA use `docs/ui-manual-test-plan.md`, which starts both servers and explicitly avoids re-indexing; the 2-3 minute camera-on demo outline is `docs/demo-plan.md`.

## Troubleshooting and demo

- `POST /api/v1/chat/sessions/{id}/messages` returns 503: inspect the backend console for the exception type and stack trace; check PostgreSQL/migrations, that `chromadb` dependencies installed in the active environment, Ollama is reachable at `OLLAMA_BASE_URL`, and both model names appear in `ollama list`. The API response intentionally hides infrastructure details.
- No sources or insufficient-evidence response: verify `CHROMA_PERSIST_DIRECTORY` and `RAG_COLLECTION_NAME` refer to the existing indexed collection, then check embedding model compatibility and retrieval threshold. Don't clear or rebuild the collection as a first troubleshooting step.
- Migration connection fails: verify `DATABASE_URL` and that PostgreSQL is accepting connections before running the Alembic command.
- Docker Compose fails: Docker Desktop must be running. The compose backend needs host Ollama at `host.docker.internal:11434`; index only if that volume is not already populated.

For a short demo, create a fresh conversation, ask a grounded product question, open its cited source, ask an unrelated question to show abstention, then create an essay and show its real word count and sources. Keep `.env` and raw transcript passages off screen. Follow `docs/demo-plan.md` and `docs/ui-manual-test-plan.md`.

## Assignment audit

See `docs/assignment-audit.md` for a requirement-by-requirement status matrix and verification limits. The referenced assignment PDF was not available in the workspace during the audit; compare this matrix to the original PDF before submission.
