# Cloud Agent Workflow (Option A): One Agent, Three Steps

This is the official way to produce a new topic in this repository using a **single
Cursor cloud agent**. It implements the "**Option A**" pipeline: one model, one context,
running the full content→image pipeline end to end.

- **Model:** `GPT-5.4 High`
- **Shape:** one cloud agent does all three steps (no orchestrator, no sub-agents)
- **Output:** the two required artifacts per topic — a **summary diagram (`.png`)** and a
  **detailed markdown (`.md`)** — committed to a topic folder and linked in its `README.md`.

> Why Option A here: this repo's deliverable is exactly a 3-step pipeline
> (read web → write notes → make an image-ready summary → render a sketchbook image).
> A single cloud agent maps onto that shape with the least token overhead, because there is
> no orchestrator context and no cross-agent hand-offs to re-send content.

---

## The three steps (one agent performs all of them)

| Step | Purpose | Produced by the agent using |
| --- | --- | --- |
| 1. Research + write | Read authoritative internet sources and write the **detailed `.md`** | web search/fetch tools + writing |
| 2. Summarize | Condense the notes into a short, **image-ready prompt** for the diagram | the same context (no extra model) |
| 3. Render | Turn that prompt into the **sketchbook `.png`** | the image-generation tool |

Note: step 3 uses an **image-generation tool**, not a chat model. `GPT-5.4 High` orchestrates
the run and writes steps 1–2; the image itself is produced by the agent's image tool.

---

## Why GPT-5.4 High (token economy)

- Strong "High" reasoning model that produces **good content** for step 1.
- **Cheaper per token** than the flagship Opus / 5.5 tiers, so unattended runs stay affordable.
- Avoid **"Fast"** variants for this job: "Fast" is a speed/priority tier — it does **not**
  reduce token count and often costs the same or more.
- Single-agent (Option A) avoids the orchestrator + hand-off token overhead that the
  sub-agent approach (Option B) incurs.

Token-saving habits for each run:
- Fetch each web page **once** and reuse it; don't re-read large pages repeatedly.
- **Cap output length** (e.g. target a focused detailed note rather than an exhaustive one).
- Keep the step-2 image prompt **short** — it only needs the visual structure, not the full notes.

---

## Launch prompt (copy/paste into a new cloud agent set to GPT-5.4 High)

```text
You are a single cloud agent creating ONE sketchbook-style learning topic for this repo,
end to end. Use this repository's existing rules and style.

Model: GPT-5.4 High. Do all steps yourself in one context (Option A — no sub-agents).

Inputs:
- Topic: <topic>
- Audience: <beginner/intermediate/advanced>
- Depth: <overview/production-grade>
- Subject folder: <existing folder like osi/ or a new <subject>/ folder>

Follow strictly:
- docs/sketchbook-style-guide.md
- docs/system-design-note-template.md
- docs/content-workflow.md
- docs/cursor-instructions.md
- .cursor/rules/sketchbook-learning-notes.mdc

Step 1 — Research + write (the detailed .md):
- Read authoritative sources from the web (RFCs, MDN, vendor docs, standards).
- Write <nn>-<topic-slug>.md following the template: learning goal, component cards,
  mandatory end-to-end flow, reliability, security, operations checklist, key takeaways,
  glossary, and a "Sources & further reading" section with links.

Step 2 — Summarize into an image-ready prompt:
- Condense the notes into a SHORT sketchbook-diagram prompt (panels/cards, arrows,
  flow strip, checklist callouts). Keep it concise; it only needs visual structure.

Step 3 — Render the summary diagram (.png):
- Use the image-generation tool to create <topic-slug>.png in the subject folder,
  in the repo's handwritten/sketchbook visual style.

Packaging:
- Cross-link the .png and .md to each other.
- Update (or create) the subject folder README.md table mapping diagram <-> detailed notes.
- Validate against docs/sketchbook-style-guide.md and report a short compliance checklist.

Token economy:
- Fetch each page once and reuse it; cap output length; keep the image prompt short.

Git:
- Commit on a cursor/<descriptive-name>-0d30 branch, push, and open a PR.
```

---

## Definition of done

A run is complete when the topic folder contains **both** artifacts, they are cross-linked,
the folder `README.md` table is updated, and the diagram passes the style-guide checklist in
`docs/sketchbook-style-guide.md`.

## When to use Option B instead

Only when you specifically need a **different model per text step** (e.g. one model writes,
a different one summarizes). That control adds orchestrator + hand-off token overhead, so for
the standard content→image pipeline in this repo, prefer Option A.
