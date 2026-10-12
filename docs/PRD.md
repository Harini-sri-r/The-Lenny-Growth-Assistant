# Product requirements and forward deployment brief

## User and problem

Product managers, founders, growth teams, and researchers need to turn Lenny's Podcast and Newsletter advice into traceable decisions and reusable writing. Finding relevant advice, checking its context, and turning it into a polished deliverable takes manual searching across a large archive.

## Success metrics

- **Grounded answer rate:** every substantive answer includes citations mapped to retrieved passages; unsupported questions return the explicit insufficient-evidence response.
- **Time to first useful answer:** a local evaluator can sign in, ask a covered product question, and inspect its source in under two minutes after startup.
- **Operational handoff:** a fresh evaluator can configure, migrate, start, and test the app using the README without rebuilding existing local vector data.

## Assumptions

- The evaluator uses a single local machine and an existing, licensed transcript archive.
- Local Ollama is the required demo path; cloud providers remain optional and depend on owner credentials and quota.
- PostgreSQL is persistent storage; browser workspaces are authenticated accounts, not a production identity-provider boundary.
- Transcript licenses prohibit raw archive redistribution and commercial reuse of raw contents.

## Scope and exclusions

Included: authenticated accounts, isolated persisted conversations, grounded RAG answers and abstention, Pi Coding Agent/Claude Agent SDK integrations, provider configuration, Ship 30 generation, saved Markdown/HTML artifacts, and a responsive workspace. Excluded: public-signup hardening (rate limiting, email verification, password reset, CAPTCHA), billing, multi-tenant deployment operations, arbitrary artifact code execution, and vector-index rebuilds during routine setup.

## Main flow and acceptance criteria

1. A user creates an account or signs in, then sees only their own conversations and artifacts.
2. They start or resume a conversation, ask a question, inspect cited sources, and receive clear abstention when evidence is insufficient.
3. They can search, rename, delete conversations, and continue a thread with prior turns used only as untrusted reference context.
4. They can generate and reopen a citation-validated Ship 30 essay and view Markdown or isolated HTML beside chat.
5. Provider UI reflects configured route/model and does not imply connectivity from configuration alone.

## Risks and trade-offs

- Retrieval/model quality affects citation usefulness; labels prove source mapping, not semantic entailment.
- Local-model latency and essay completion vary with hardware and prompt size.
- Browser workspace IDs were replaced by server-verified accounts; existing anonymous sessions remain stored after migration but are not automatically assigned to an account.
- Authentication uses scrypt password hashes, hashed opaque database session tokens, HttpOnly cookies, SameSite=Lax, and CSRF tokens on state-changing requests. Production must enable Secure cookies and HTTPS. Email verification, recovery, and rate limiting are not implemented.
- Generated HTML is untrusted and remains in a sandboxed iframe with restrictive CSP.

## Implementation plan and status

The local RAG/API/frontend path, additive account migrations, cookie auth, ownership checks, tests, and documentation are implemented. Remaining release checks are a real Pi→Ollama request through the running app, manual browser verification, clean-clone/Docker startup verification, and recording the required demo. Automated tests do not prove those live checks.
