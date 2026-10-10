# Design direction

The application uses an editorial workspace layout with warm paper tones, restrained olive accents, and clear conversation hierarchy. A compact left rail lists independent conversations. The center column contains the message history, citations, loading/error feedback, and Ship 30 for 30 generation controls. The right rail keeps saved artifacts visible alongside chat.

Answers show source labels with source title, type, path, and a link when the source index includes a URL. Insufficient-evidence messages show no citations. Artifacts show their recorded word count and supporting sources. Markdown is rendered as escaped preformatted text; HTML is previewed in a sandboxed iframe with a restrictive CSP so generated markup cannot execute scripts or access the parent app.

Responsive styles hide secondary rails on narrow screens while preserving the active conversation and composer. The current workspace ID is browser-local and should be replaced by authenticated profile/session UI before a public launch.
