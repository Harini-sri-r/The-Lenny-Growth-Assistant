# Take-home requirement audit

**Audit basis:** The referenced Forward Deployed Engineer Take-Home Assignment PDF was not available in the repository or uploaded attachment directory during this audit. This matrix maps the requirements listed in the accompanying request; verify against the PDF before submission.

Status meanings: **Implemented and verified** means present and exercised by a repository test or direct check; **Implemented but unverified** means code/config exists but its required live integration or end-to-end behavior has not been exercised; **Missing** means no complete implementation exists.

| Requirement | Status | Evidence and notes |
|---|---|---|
| FastAPI backend | Implemented and verified | `backend/app/main.py`, routes in `backend/app/api/routes/`; health and chat endpoint tests in `backend/tests/`. |
| Claude Agent SDK or Pi Coding Agent | Implemented but unverified | `backend/app/agents/lenny_agent.py` integrates Claude Agent SDK with a read-only in-process transcript-search MCP tool and chat configuration via `AGENT_FRAMEWORK`; `backend/tests/test_lenny_agent.py` verifies orchestration with a fake SDK. SDK package/auth and live Claude execution are not available here. |
| PostgreSQL conversations, sessions, timestamps, user metadata | Implemented and migration verified | `backend/app/models/chat.py`, `backend/app/api/routes/chat.py`, `backend/migrations/versions/0001_chat_and_artifacts.py`; persistence/session tests pass, and PostgreSQL revision `0001_chat_artifacts` was applied and queried successfully. A live HTTP API startup against PostgreSQL was not exercised. |
| Cloud provider and local Ollama, selectable by configuration | Implemented but unverified | `backend/app/agents/providers.py`, `backend/app/core/config.py`, `.env.example`; adapters/config exist, but Ollama was unreachable and no cloud request was made. |
| Transcript KB, ingestion, retrieval, citations, insufficient evidence | Implemented but unverified | `backend/app/rag/`, `backend/app/services/rag.py`, `scripts/ingest_transcripts.py`; synthetic/unit tests and real archive validation pass, while ChromaDB is not installed in this Python environment and Ollama is unreachable. A stored-vector dimension guard avoids accidental destructive re-indexing to address query/index model mismatches. |
| Ship 30 for 30 skill producing ~1,250 grounded words | Implemented but unverified | `backend/app/skills/ship30_for_30/SKILL.md`, `backend/app/api/routes/artifacts.py`; the prompt sets the target, endpoint refuses missing evidence and records actual word count. Live generated output and word target remain unverified. |
| Markdown and HTML/CSS artifacts with in-app viewer and isolation | Implemented but unverified | `ChatArtifact` persistence in `backend/app/models/chat.py`, generation in `backend/app/api/routes/artifacts.py`, viewer in `frontend/src/pages/App.tsx` uses sandboxed iframe and restrictive CSP. Browser-level isolation is not manually tested. |
| Docker Compose reproducible startup | Implemented but unverified | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`; migrations run before serving, API health is configured, and frontend uses lockfile-based `npm ci`. Compose configuration parses, but Docker Engine was unavailable, so images and the stack were not built. |
| `.env.example` and secret/data/index Git exclusions | Implemented but unverified | `.env.example`, `.gitignore`, `.dockerignore`; dataset, Chroma directories, `.env`, and local SQLite files are excluded by patterns. Workspace has no `.git` metadata, so Git tracking status cannot be checked. |
| Structured logs | Implemented but unverified | `backend/app/core/logging_config.py`, request middleware in `backend/app/main.py`; logs omit request bodies, query strings, and transcript contents. Output format has not been inspected in a live server run. |
| Resilient service errors | Implemented and verified | `backend/app/main.py`, `backend/app/api/routes/chat.py`; endpoint tests verify sanitized provider and database failures. Live outages/models remain untested. |
| Database migrations | Implemented and verified | Offline SQL generation succeeded and PostgreSQL applied revision `0001_chat_artifacts`; the live database reports that revision. |
| README, PRD, design, architecture | Implemented but unverified | `README.md`, `docs/PRD.md`, `docs/design.md`, `docs/architecture.md` updated for current implementation. Original assignment PDF was unavailable for direct comparison. |
| Agent transcripts including failures/corrections | Implemented and verified | `agent-transcripts/implementation-log.md` records observed failures/corrections without secrets or transcript excerpts; it is a concise engineering record rather than a raw conversation export. |
| Automated tests | Implemented and verified | `backend/tests/`; final run: 42 passed. `npm exec -- tsc --noEmit -p tsconfig.json` passes. Vitest/Vite execution is blocked because esbuild cannot read ancestor directory `../../../../..` in this sandbox; Node can read the config directly, indicating a sandbox path traversal restriction. |
| UI manual test plan | Implemented and verified | `docs/ui-manual-test-plan.md` includes chat, citations, session isolation, error, essay, and sandbox checks; the manual checks themselves remain to be run. |
| 2-3 minute camera-on YouTube demo plan | Implemented and verified | `docs/demo-plan.md` includes timed outline and publication hygiene; the video itself remains for the owner to record and approve. |
| React + TypeScript + Vite retention | Implemented but unverified | `frontend/package.json`, `frontend/src/`; TypeScript no-emit check passes. Vitest and production build fail during esbuild startup when it attempts to read ancestor directory `../../../../..`; Node can read the config directly, which indicates the sandbox path boundary. |

## Deadline priorities (12 October 2026)

1. Run frontend tests/build outside the restricted sandbox and complete manual UI validation.
2. Install declared dependencies with `python -m pip install -r backend/requirements.txt`; verify ChromaDB and Ollama, then exercise existing-index retrieval and citations without re-indexing.
3. Verify live HTTP startup, Claude Agent SDK tool use, and HTML iframe isolation.
4. Complete manual UI QA; verify generated essays are near the target length and source-grounded.
5. Compare this matrix with the original assignment PDF once available.
