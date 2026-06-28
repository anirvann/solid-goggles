# Cursor Instructions: Sketchbook Visual Learning Notes

Use these instructions when asking Cursor to create or extend learning notes in this repository.

## Output contract: every topic produces TWO artifacts

For **each topic**, always generate both:

1. **Summary diagram** (`.png`) — the sketchbook-style visual overview (the quick glance).
2. **Detailed markdown** (`.md`) — the in-depth written reference that expands on every item in the diagram, including a **"Sources & further reading"** section with links to authoritative references (RFCs, MDN, vendor docs, etc.).

The image is the **summary**; the markdown is the **detailed document**. Keep them in the same topic folder and cross-link them (README table + links inside each file).

### File/folder conventions

- One folder per subject area (e.g. `docs/samples/osi/`).
- Diagram: `<topic-slug>.png`
- Detailed notes: `<nn>-<topic-slug>.md` (numbered for reading order)
- A folder `README.md` with a table mapping each diagram to its detailed notes.

## Master prompt (copy/paste)

```text
You are creating visual-first learning notes in a sketchbook style.

Follow these files strictly:
- docs/sketchbook-style-guide.md
- docs/system-design-note-template.md
- docs/content-workflow.md

For EVERY topic, produce BOTH artifacts:
1) A summary diagram (.png) in sketchbook style.
2) A detailed markdown (.md) that expands on each item in the diagram and
   ends with a "Sources & further reading" section of authoritative links.

Diagram rules:
1) Visuals first: use section cards, arrows, flow strips, and checklist blocks.
2) Keep prose short; no long paragraphs.
3) Use handwritten-style heading/body font guidance from style guide.
4) Preserve free-flow composition while maintaining clear reading order.
5) Include practical production insights: failure modes, observability, security, and operations.
6) Include an end-to-end flow and key takeaways.

Detailed markdown rules:
1) Cover every concept shown in the diagram, with real depth (tables, sequences, examples).
2) Include hands-on commands where relevant.
3) Include a "Key takeaways" section.
4) Include a "Sources & further reading" section with links.
5) Cross-link the diagram and the markdown to each other.

When I provide a topic, generate:
- the summary diagram (or its image-generation prompt)
- the detailed markdown file with sources
- a folder README table linking diagram <-> detailed notes
- a brief validation checklist against the style guide
```

## Topic-specific prompt template

```text
Create a sketchbook-style visual learning note for:
Topic: <topic>
Audience: <beginner/intermediate/advanced>
Depth: <overview/production-grade>
Constraints: <optional constraints>

Output requirements:
- Produce BOTH a summary diagram (.png) and a detailed markdown (.md)
- Use docs/system-design-note-template.md structure
- Include component cards and end-to-end flow
- Include reliability, security, and operations sections
- Detailed markdown must end with "Sources & further reading" links
- Cross-link the diagram and the markdown; update the folder README table
```

## Quality gate prompt

Use this after generation:

```text
Review the created note against docs/sketchbook-style-guide.md.
Return:
1) what matches,
2) what is missing,
3) exact edits needed to reach style compliance.
```

## Iteration prompt for future topics

```text
Add a new topic note without changing previous notes.
Reuse the same visual language, card hierarchy, and section ordering.
Ensure consistency of tone and production-readiness checklist.
```
