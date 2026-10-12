# Architecture

## Authentication and ownership

`/api/v1/auth/register`, `/login`, `/me`, and `/logout` provide accounts and revocable opaque sessions. Passwords are hashed with Python `scrypt`; raw session tokens are random and only their SHA-256 hashes are stored in PostgreSQL. Login rotates any presented browser session token. The browser receives an HttpOnly session cookie and a separate CSRF cookie. Mutating authenticated requests require the matching `X-CSRF-Token`; SameSite is Lax and the session cookie is Secure when the request uses HTTPS or `AUTH_COOKIE_SECURE` is enabled. Sessions expire after `AUTH_SESSION_DAYS` and logout revokes the database token.

Every chat, message, rename/delete, artifact-generation, and artifact-list request derives ownership from the authenticated `ChatUser`, never from a caller-supplied user ID. Session lookup filters by both session ID and authenticated owner. PostgreSQL cascades session deletion to messages/artifacts. Migrations are additive: existing anonymous users and histories are retained, but lack email/password credentials and are not exposed through authenticated routes or automatically claimed by a new account.

## Request and model flow

The React/Vite client calls FastAPI under `/api/v1`. Chat history, timestamps, sources, and artifacts persist in PostgreSQL through SQLAlchemy; Alembic migrations add account credentials, auth sessions, message retry IDs, and assistant reply links without replacing existing chat tables.

For `AGENT_FRAMEWORK=rag_service`, chat embeds the question using Ollama, retrieves cosine-ranked ChromaDB passages, and calls the selected LLM adapter. For `pi_coding_agent`, the service retrieves and labels passages then invokes Pi through its one-shot JSON event stream with tools/session persistence disabled. `claude_agent_sdk` uses its read-only in-process MCP transcript-search tool. Source IDs are checked against retrieved references, and empty retrieval yields an explicit insufficient-evidence response. Prior conversation turns are included only as untrusted context for resolving follow-ups; they are not evidence.

The local `.env` selects Pi Coding Agent plus Ollama/Qwen. `.env.example` provides safe generic defaults for a fresh local setup; Pi/Ollama additionally needs a Pi `models.json` entry matching `OLLAMA_MODEL`. `/api/v1/providers` reports configuration only and does not probe connectivity. Optional cloud adapters are implemented, but live cloud access depends on owner credentials, project access, and quota.

## Data, artifacts, and security

The licensed source archive remains external to Git at `TRANSCRIPTS_PATH`. `index.json` metadata, deterministic chunk IDs, embedding, upsert, retrieval threshold, and source references are handled in `backend/app/rag`. Routine startup reuses existing ChromaDB data; `--reindex` clears and rebuilds it and is not part of this workflow.

Markdown is rendered with React elements for headings, lists, tables, code, links, emphasis, and literal citations; raw HTML stays inert text. Chat artifacts can be generated as Markdown or complete HTML/CSS documents using the recent conversation to resolve intent and retrieved transcript passages as the evidence source. Saved artifacts belong to the authenticated user/session and are listed on app load so they can be reopened after refresh.

HTML artifacts are untrusted. The viewer places them in an iframe with an empty `sandbox` (no scripts, forms, popups, downloads, or same-origin privileges) and injects a CSP that denies scripts, network connections, remote resources, nested frames, objects, forms, and base URL changes. Inline CSS and `data:` images are allowed for presentation. The iframe has an opaque origin and receives no app auth tokens. Markdown raw HTML stays inert text. Downloaded HTML leaves this viewer boundary, so users should treat a downloaded file as untrusted. The app is intended for evaluation and needs further deployment hardening before public exposure.

## Operations

Docker Compose starts PostgreSQL, applies Alembic migrations, checks API health, and serves the frontend. Backend logs use structured request IDs and omit credentials, message bodies, prompts, and transcript text. These deployment steps are documented but need fresh-machine verification; unit tests do not establish clean-clone or Docker success.
