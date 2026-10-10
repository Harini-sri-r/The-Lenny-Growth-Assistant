# Architecture

## Request flow
The React/Vite client creates a persistent browser workspace ID and calls FastAPI under `/api/v1`. Chat sessions, user and assistant messages, timestamps, grounding state, citations, and generated artifacts are stored in PostgreSQL through SQLAlchemy. Alembic owns schema changes; apply `alembic -c backend/alembic.ini upgrade head` before serving the API. A SQLAlchemy database exception returns a safe 503.

For standard RAG chat, the service embeds the query through Ollama, retrieves cosine-ranked ChromaDB passages, filters by configured minimum similarity, and calls the selected LLM adapter (Ollama or OpenAI). The system prompt limits answer evidence to retrieved passages and source labels not present in the retrieved set are removed. Empty retrieval returns an explicit insufficient-evidence response without calling the LLM.

When `AGENT_FRAMEWORK=claude_agent_sdk`, chat uses `ClaudeResearchAgent`. It exposes a single read-only in-process MCP tool, `search_transcripts`, to Claude Agent SDK and permits no filesystem or shell tools. The Ship 30 for 30 endpoint uses this agent and its dedicated skill prompt to retrieve evidence and generate Markdown or HTML/CSS artifacts.

## Data and configuration
The existing archive remains at `lennys-newsletterpodcastdata-main/`; set `TRANSCRIPTS_PATH` to configure its location. `index.json` supplies document title/type/date and available URL and descriptive metadata. Chunk identifiers are deterministic. On a normal rerun, compatible existing records may be reused; missing or incompatible chunks are embedded and upserted. Stale-record cleanup occurs only after indexing succeeds, so a failed run does not reach cleanup. `--reindex` explicitly clears and rebuilds the Chroma collection. These are implementation behaviors, not evidence that live indexing, reuse, or cleanup has been verified.

The persistent Chroma directory is configurable with `CHROMA_PERSIST_DIRECTORY` and ignored by Git. `.env` secrets and the licensed data directory are also ignored. No absolute developer machine path is required.

## Artifact isolation
Markdown previews are displayed as escaped text. HTML/CSS previews use an iframe with an empty `sandbox` attribute (no scripts or same-origin privileges) and a restrictive Content Security Policy that disables network resources by default. Do not add `allow-scripts` or `allow-same-origin` or inject generated markup into the parent document.

## Operations and limitations
Docker Compose starts PostgreSQL, runs Alembic migrations in the backend container, checks API health, and serves the frontend separately. The frontend image installs exactly from `package-lock.json` using `npm ci`. Backend request logs use JSON fields and intentionally omit request bodies, prompts, transcript passages, and query strings. Browser workspace IDs separate demo histories but are not user authentication; public deployment requires a real identity provider and authorization.
