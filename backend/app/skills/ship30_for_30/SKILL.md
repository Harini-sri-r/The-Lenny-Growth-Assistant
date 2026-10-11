---
name: ship30-for-30-grounded-essay
description: Create a Ship 30 for 30 style essay grounded in retrieved Lenny podcast and newsletter passages.
---

# Ship 30 for 30 grounded essay skill

Write one useful, clear essay of 1,150–1,350 words (aim for approximately 1,250) for the requested audience and topic. Use the read-only `search_transcripts` tool before drafting and retrieve evidence about the topic. Use the provided source passages as the factual basis for advice attributed to Lenny or podcast guests.

Structure the essay with a specific title and a strong opening hook that names the reader's problem and gives them a reason to continue. Build a clear narrative progression: frame the problem, develop one central argument with practical examples and actions, then end with a concise takeaway the reader can use. Use descriptive, skimmable headings; use bullets for compact steps or checklists where they improve readability; apply bold emphasis sparingly to key ideas. Prefer plain language and concrete recommendations. Do not invent quotations, people, examples, metrics, URLs, or citations. Support claims attributed to Lenny or podcast guests with the exact evidence labels supplied by the tool (for example `[S1]`), and keep each citation next to the claim it supports. If evidence is thin, clearly state the limitation and keep claims narrow. If the tool finds no relevant evidence, do not write a pretend grounded essay; say that the library did not provide sufficient evidence.

Return exactly one essay. Do not repeat a title, paragraph, section, or complete draft; when asked to continue, return only genuinely new supported material. Cite the passage that supports each factual claim immediately after that claim, using the application's exact `[S#]` label mapped to the supplied source metadata. A citation is not sufficient merely because its source is related: verify that the cited passage supports the named person, company, metric, and example. If it does not, omit or narrow the claim. Never invent personal experience or imply that the writer personally witnessed an event.

Return Markdown only when the requested format is Markdown. For HTML, return a complete self-contained HTML document with inline CSS, semantic elements, no JavaScript, no remote resources, and the same evidence citations. Keep the output within 1,150–1,350 words of essay prose (headings and citations do not count toward that target).
