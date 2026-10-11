# Product requirements

## Product goal
Lenny Growth Assistant helps product managers and startup operators explore advice in Lenny's Podcast and Newsletter archive through grounded chat, citations, and a dedicated Ship 30 for 30 essay skill.

## User experience
- Create independent conversations and return to their persisted history.
- Ask product and growth questions; receive answers only when relevant indexed evidence is found, with source references.
- Generate an approximately 1,250-word essay for a specified audience using the Ship 30 for 30 skill and retrieved transcript evidence.
- Save Markdown or HTML/CSS essays as artifacts and inspect them in the Artifact Viewer.
- Use Ollama by default for local chat and Ship 30 generation without cloud credentials. OpenAI and Claude Agent SDK are optional cloud providers; missing credentials or failed cloud calls fall back to Ollama. Live cloud generation requires valid credentials.

## Current implementation
FastAPI chat/session routes persist workspace metadata, messages, citations, and artifacts. Transcript loading, chunking, embeddings, ChromaDB indexing, retrieval thresholds, source metadata, and insufficient-evidence behavior are implemented. The frontend is React/TypeScript/Vite. Artifact HTML is displayed in a sandboxed iframe with a restrictive CSP. PostgreSQL schema changes use Alembic.

## Constraints and known limits
- The bundled public starter dataset permits personal non-commercial use; raw transcript files may not be redistributed or used commercially. Do not add it to source control.
- Browser-generated workspace IDs are not authentication; the current experience is for local/demo use.
- Live PostgreSQL, ChromaDB, Ollama models, Claude Agent SDK authentication, cloud generation, full Docker startup, and production browser behavior require manual verification in a configured environment.
- The essay target is approximate. Each artifact records its actual word count and retrieved references; the app does not claim a generated length is exact.
