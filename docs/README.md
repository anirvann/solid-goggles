# Visual Learning Docs

This folder contains the framework for sketchbook-style technical learning material.

## Start here

1. Read `sketchbook-style-guide.md`
2. Use `system-design-note-template.md`
3. Follow `content-workflow.md`
4. Use prompts from `cursor-instructions.md`
5. To run it end to end with one cloud agent, follow `cloud-agent-workflow.md` (Option A, GPT-5.4 High)

## Two artifacts per topic

Every topic produces **both**:

- a **summary diagram** (`.png`) — the sketchbook-style visual overview, and
- a **detailed markdown** (`.md`) — the in-depth reference with a `Sources & further reading` section.

The image is the summary; the markdown is the detailed document. Keep them in the same
topic folder and cross-link them.

## Example

See the root-level `osi/` folder for a complete example. One subject is split into a summary pair plus one pair per subtopic:
- `osi-overview-sketchbook.png` + `00-osi-model-overview.md` (summary: how the parts fit together)
- `physical-layer-sketchbook.png` + `01-physical-layer.md`, through
- `application-layer-sketchbook.png` + `07-application-layer.md`
- `devices-across-layers-sketchbook.png` + `08-devices-and-security-across-layers.md`

## Future topics

As systems-design topics are added, create a folder per subject and produce both the
summary diagram and the detailed markdown using the same style and structure.
