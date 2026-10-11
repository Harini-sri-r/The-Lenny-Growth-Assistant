# Take-home requirement audit

**Audit basis:** The referenced Forward Deployed Engineer Take-Home Assignment PDF was not available in the repository or uploaded attachment directory during this audit. This matrix maps the requirements listed in the accompanying request; verify against the PDF before submission.

Status meanings: **Implemented and verified** means present and exercised by a repository test or direct check; **Implemented but unverified** means code/config exists but its required live integration or end-to-end behavior has not been exercised; **Missing** means no complete implementation exists.

| Requirement | Status | Evidence and notes |
|---|---|---|
| FastAPI backend | Implemented and verified | `backend/app/main.py`, routes in `backend/app/api/routes/`; health and chat endpoint tests in `backend/tests/`. |
| Claude Agent SDK or Pi Coding Agent | Pi implemented; live execution unverified | `backend/app/agents/lenny_agent.py` has an opt-in Pi adapter using Pi's documented JSON event stream; routing supports Gemini and Ollama. Mocked boundary/routing/citation tests pass. Pi CLI is not installed in this environment, so no live response was generated. The existing Claude Agent SDK adapter remains optional. |
| PostgreSQL conversations, sessions, timestamps, user metadata | Implemented and migration verified | `backend/app/models/chat.py`, `backend/app/api/routes/chat.py`, `backend/migrations/versions/0001_chat_and_artifacts.py`; persistence/session tests pass, and PostgreSQL revision `0001_chat_artifacts` was applied and queried successfully. A live HTTP API startup against PostgreSQL was not exercised. |
| Cloud provider and local Ollama, selectable by configuration | Implemented but unverified | `backend/app/agents/providers.py`, `backend/app/core/config.py`, `.env.example`; adapters/config exist, but Ollama was unreachable and no cloud request was made. |
| Transcript KB, ingestion, retrieval, citations, insufficient evidence | Implemented but unverified | `backend/app/rag/`, `backend/app/services/rag.py`, `scripts/ingest_transcripts.py`; synthetic/unit tests and real archive validation pass, while ChromaDB is not installed in this Python environment and Ollama is unreachable. A stored-vector dimension guard avoids accidental destructive re-indexing to address query/index model mismatches. |
| Ship 30 for 30 skill producing ~1,250 grounded words | Implemented but unverified | `backend/app/skills/ship30_for_30/SKILL.md`, `backend/app/api/routes/artifacts.py`; the prompt sets the target, endpoint refuses missing evidence and records actual word count. Live generated output and word target remain unverified. |
| Markdown and HTML/CSS artifacts with in-app viewer and isolation | Implemented but unverified | `ChatArtifact` persistence in `backend/app/models/chat.py`, generation in `backend/app/api/routes/artifacts.py`, viewer in `frontend/src/pages/App.tsx` uses sandboxed iframe and restrictive CSP. Browser-level isolation is not manually tested. |
| Docker Compose reproducible startup | Implemented but unverified | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`; migrations run before serving, API health is configured, and frontend uses lockfile-based `npm ci`. Compose configuration parses, but Docker Engine was unavailable, so images and the stack were not built. |
| `.env.example` and secret/data/index Git exclusions | Implemented but unverified | `.env.example`, `.gitignore`, `.dockerignore`; dataset, Chroma directories, `.env`, and local SQLite files are excluded by patterns. This is a Git repository; `git check-ignore` confirms the archive and Chroma data paths are ignored, and neither appears in working-tree status. |
| Structured logs | Implemented but unverified | `backend/app/core/logging_config.py`, request middleware in `backend/app/main.py`; logs omit request bodies, query strings, and transcript contents. Output format has not been inspected in a live server run. |
| Resilient service errors | Implemented and verified | `backend/app/main.py`, `backend/app/api/routes/chat.py`; endpoint tests verify sanitized provider and database failures. Live outages/models remain untested. |
| Database migrations | Implemented and verified | Offline SQL generation succeeded and PostgreSQL applied revision `0001_chat_artifacts`; the live database reports that revision. |
| README, PRD, design, architecture | Implemented but unverified | `README.md`, `docs/PRD.md`, `docs/design.md`, `docs/architecture.md` updated for current implementation. Original assignment PDF was unavailable for direct comparison. |
| Agent transcripts including failures/corrections | Implemented and verified | `agent-transcripts/implementation-log.md` records observed failures/corrections without secrets or transcript excerpts; it is a concise engineering record rather than a raw conversation export. |
| Automated tests | Verified | Backend: 134 passed. Frontend: 13 passed after an approved out-of-sandbox run. Production build passed. `git diff --check` passed. |
| UI manual test plan | Implemented and verified | `docs/ui-manual-test-plan.md` includes chat, citations, session isolation, error, essay, and sandbox checks; the manual checks themselves remain to be run. |
| 2-3 minute camera-on YouTube demo plan | Implemented and verified | `docs/demo-plan.md` includes timed outline and publication hygiene; the video itself remains for the owner to record and approve. |
| React + TypeScript + Vite retention | Implemented and verified | `frontend/package.json`, `frontend/src/`; frontend tests and production build pass. |

| Pi Coding Agent plus Gemini and local Ollama selection | Implemented; live provider behavior unverified | Select `AGENT_FRAMEWORK=pi_coding_agent`; select provider with `LLM_PROVIDER=gemini` or `ollama`. Pi uses its JSON event stream; Ollama requires Pi `models.json`. `pi` is absent here; test doubles verify JSON extraction, citation preservation/rejection, errors, timeouts, and both routes. |

## Deadline priorities (12 October 2026)

1. Install Pi and validate one local Ollama request with `models.json`; verify one Gemini request only if credentials/quota are available.
2. Install missing backend requirements and run the mandatory live Ollama/Chroma retrieval demo against the existing index; do not re-index unnecessarily.
3. Complete manual UI QA, test persisted PostgreSQL sessions in the running API, and verify essay generation/artifact viewer.
4. Record the demo video; the plan exists, but the video itself is not in the repository.
5. Compare this matrix with the original assignment PDF once available; it was not provided for direct comparison.
