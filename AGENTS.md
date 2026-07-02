# AGENTS.md

Guidance for AI agents working in this repository (`solid-goggles`).

## What this repo is

Sketchbook-style visual learning notes for technical topics. Each subject lives
in its own root-level folder (e.g. `osi/`, `cdn/`).

## The core rule: paired artifacts (markdown + summary image)

Every unit of content is delivered as a **pair**:

1. A **summary diagram** (`.png`) — hand-drawn/whiteboard sketchbook style.
2. A **detailed markdown** (`.md`) — the in-depth reference.

Keep both in the same topic folder, cross-link them, and add a row to that
folder's `README.md` table (diagram ↔ notes). Also link new folders from the
root `README.md`.

## Topics can have subtopics → multiple markdown files AND multiple images

A topic is **not limited to a single markdown file or a single image**. Every
topic can be broken into as many subtopics as the material needs, and **each
subtopic is its own paired artifact** — its own detailed `.md` **and** its own
summary `.png`. This is expected and encouraged; do not force a large topic into
one file or one diagram just to keep the count down.

- Split by subtopic whenever a single note would become too long or cover
  clearly distinct ideas.
- Name files with a numeric prefix and a descriptive slug, e.g.
  `01-<subtopic>.md`, `02-<subtopic>.md`, `03-<subtopic>.md`, each with a
  matching `*-sketchbook.png`.
- The output for one topic can therefore be **multiple markdown files and
  multiple summary images** living together in the same topic folder.
- List every subtopic pair as its own row in the folder `README.md` table.

Example (the `cdn/` folder):

```
cdn/
  01-cdn-fundamentals-and-request-routing.md   ↔  cdn-architecture-request-routing-sketchbook.png
  02-cdn-edge-computing.md                     ↔  cdn-edge-compute-sketchbook.png
  03-cdn-security-and-multi-cdn-resiliency.md  ↔  cdn-security-multicdn-sketchbook.png
  README.md
```

## Detailed markdown must include

- A one-line learning goal near the top.
- A companion note pointing at the matching `.png`.
- Component breakdown, an end-to-end flow, and a reliability/security/ops lens.
- `Key takeaways` and a short glossary.
- A final `Sources & further reading` section with links to authoritative
  references (RFCs, vendor engineering docs/blogs, papers — not just marketing pages).

## Diagram style

Follow `docs/sketchbook-style-guide.md`: off-white ruled paper, hand-lettered
blue title, limited blue/green/orange/purple palette, rounded boxes, short
bullets, arrows/flow strips, at least one end-to-end sequence. Verify the
rendered text is legible and technically accurate before committing.

## Also follow

- `docs/system-design-note-template.md`
- `docs/content-workflow.md`
- `.cursor/rules/sketchbook-learning-notes.mdc`

## Conventions

- Branch names: `cursor/<descriptive-name>-<suffix>`; open a PR per branch.
- Commit docs + images together with a descriptive message.
- Prefer editing existing notes over duplicating topics.

## Testing expectations

These are docs/image changes. "Testing" = verifying diagram text accuracy and
legibility, and confirming relative links/image paths resolve. No build or unit
test suite applies unless one is added later.
