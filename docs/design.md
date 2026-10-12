# Design direction

## Visual system

The workspace uses warm paper and cream surfaces, espresso navigation, charcoal text, and restrained olive accents. Compact editorial headings support a readable sans-serif for long answers. Borders, radii, and spacing stay consistent, with focus-visible rings and reduced-motion support. Chat remains the primary surface; decoration stays restrained.

## Information architecture

- **Sidebar:** custom Lenny mark, New chat, title search, date-grouped history, per-chat rename/delete menu, configured provider/model details, and account/logout menu.
- **Conversation:** compact title bar, welcome state with real prompt actions, messages, source cards, loading/error/retry feedback, and a bottom-anchored multiline composer.
- **Artifact panel:** separate Ship 30 essay and chat-to-artifact actions; saved artifact list, title, word count, sources, Markdown or isolated HTML preview, copy, and download. On small screens the sidebar and artifact panel open over chat.
- **Authentication:** centred, responsive sign-in/create-account form with tab semantics, visible password toggle, signup confirmation, accessible mismatch feedback, busy state, and non-enumerating server errors.

## Interaction and accessibility

Enter sends, Shift+Enter inserts a newline, and actions have visible focus. Suggested prompts submit to the API. Conversation actions use keyboard-accessible native controls. Long content stays within readable line lengths; code and tables scroll within their own containers. Responsive breakpoints preserve the composer and navigation. Reduced-motion preferences reduce animation and transitions.

## Security and known limits

Account cookies are HttpOnly; state-changing requests include the CSRF token. API queries enforce account ownership. Generated Markdown uses inert React text/elements; raw HTML is only shown in a sandboxed iframe with CSP. Public launch needs further identity and abuse controls such as password recovery, email verification, and rate limiting. Browser/device testing remains a manual release check.
