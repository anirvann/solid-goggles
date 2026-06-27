# Content Workflow for New Topics

This workflow is for future systems-design topics added by the user.

## 1) Intake

For each new topic, capture:

- Topic name
- Expected audience level (beginner/intermediate/advanced)
- Primary learning objective
- Preferred depth (overview vs production-grade)

## 2) Outline the visual story

Before writing text, define the panel map:

1. Header + learning goal
2. Core architecture cards
3. Request/data flow strip
4. Reliability/scaling panel
5. Security/operations checklist
6. Key takeaways

## 3) Draft with template

- Copy `docs/system-design-note-template.md`
- Fill in only short bullets and labels first
- Add visuals/diagram structure next
- Keep explanatory prose minimal

## 4) Style enforcement

Validate against `docs/sketchbook-style-guide.md`:

- Handwritten-style typography
- Rounded cards + connector arrows
- Limited but consistent accent palette
- Free-flow arrangement with clear scan path

## 5) Technical accuracy pass

Review each panel for:

- Correct component responsibilities
- Correct sequencing and dependencies
- Realistic failure modes and observability signals
- Practical production checklist items

## 6) Final packaging

For every note, produce:

- One visual-first master note
- One short text companion (optional) if clarification is needed
- Reusable component snippets for future topics

## 7) Naming convention

Recommended filename style:

`<nn>-<topic-slug>-visual-note.md`

Examples:
- `01-load-balancer-visual-note.md`
- `02-api-gateway-visual-note.md`
- `03-cache-invalidation-visual-note.md`
