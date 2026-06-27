# Cursor Instructions: Sketchbook Visual Learning Notes

Use these instructions when asking Cursor to create or extend learning notes in this repository.

## Master prompt (copy/paste)

```text
You are creating visual-first learning notes in a sketchbook style.

Follow these files strictly:
- docs/sketchbook-style-guide.md
- docs/system-design-note-template.md
- docs/content-workflow.md

Rules:
1) Visuals first: use section cards, arrows, flow strips, and checklist blocks.
2) Keep prose short; no long paragraphs.
3) Use handwritten-style heading/body font guidance from style guide.
4) Preserve free-flow composition while maintaining clear reading order.
5) Include practical production insights: failure modes, observability, security, and operations.
6) Every note must include an end-to-end flow and key takeaways.

When I provide a topic, generate:
- a complete visual-note markdown file
- a compact diagram spec (if needed)
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
- Use docs/system-design-note-template.md structure
- Include component cards and end-to-end flow
- Include reliability, security, and operations sections
- Keep content concise and visual-first
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
