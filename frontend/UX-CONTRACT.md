# Synthetix Alpha UX Contract

This contract covers the frontend application under `frontend/`. Visual rules live in `DESIGN.md`.

## Data and mode

- Every data-dependent surface identifies mock, historical, paper, stale, or unavailable status.
- The browser reads only dashboard DTOs. It never receives credentials or calls Alpaca, Finnhub, FRED, or OpenAI directly.
- If the dashboard adapter is unavailable, the UI uses typed demo data and shows `DEMO DATA`.
- Execution may be shown as unavailable, skipped, duplicate-prevented, dry-run, submitted, or error. It must not be visually upgraded to a fill.

## Navigation and overlays

- Route titles use `{Page} — Synthetix Alpha`.
- The command palette opens with Cmd/Ctrl+K. Slash focuses the opportunity search only outside text input. Escape closes the topmost overlay.
- Opportunity details open in a modal right Sheet. It restores focus to its trigger on close and becomes full-screen on mobile.

## Tables and states

- Opportunity filters and sort are URL-ready; implementation may add route-query persistence when live filtering is connected.
- Tables keep comparison columns and use horizontal scrolling on narrow viewports.
- Major panels reserve layout space during loading. Empty and error states explain the actual data condition without raw backend errors.

## Risk and actions

- The only proposed user action is a dry pipeline request. It is disabled in demo mode and disabled by the adapter until a server-side worker can guarantee dry-run semantics.
- Current enforced controls and configuration-only governance controls are visually differentiated.
