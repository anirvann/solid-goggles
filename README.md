# solid-goggles

Sketchbook-style visual learning notes for technical topics (starting with systems design).

## Repository structure

- `docs/sketchbook-style-guide.md`  
  Visual style rules based on hand-drawn/whiteboard note aesthetics.
- `docs/system-design-note-template.md`  
  Reusable template for new visual-first learning notes.
- `docs/content-workflow.md`  
  Step-by-step workflow for adding future topics.
- `docs/cursor-instructions.md`  
  Prompting and execution guidance for using Cursor to create notes.
- `docs/cloud-agent-workflow.md`  
  Option A single cloud-agent workflow (GPT-5.4 High) for producing a topic end to end.
- `.cursor/rules/sketchbook-learning-notes.mdc`  
  Repository-level Cursor rule to keep generated content consistent.
- `AGENTS.md`  
  Instructions auto-loaded by AI agents: paired markdown+image artifacts, and how a topic can have subtopics producing multiple markdown files and multiple summary images.
- `osi/`  
  Example subject folder: sketchbook summary diagrams + detailed markdown notes for networking/OSI topics.
- `cdn/`  
  Content Delivery Network (CDN) topics: fundamentals & request routing, edge computing, and security & multi-CDN resiliency — with sketchbook diagrams + detailed notes sourced from Cloudflare, Akamai, and Fastly.
- `payments/`  
  E-commerce payment systems & payment processors: transaction flow (auth→capture→clearing→settlement), bank integration/gateways/e-wallets, reliability (idempotency, no double-charging, order confirmation), security/fraud/disputes, and a dedicated deep dive on the Indian **UPI** system — sourced from Stripe, Razorpay, PCI SSC, NPCI, and RBI.
- `maps/`  
  Maps, geospatial & real-time location systems behind ride-hailing (Uber, Ola, Rapido, Namma Yatri) and food delivery (Swiggy, Zomato, DoorDash): geospatial indexing (geohash/S2/**H3**) & spatial databases, matching/dispatch/routing (**DISCO**, **DeepRed**, DeepETA), location ingestion at scale & live updates (Kafka + **RAMEN**), how maps are made & maintained (OSM/probe fusion, map-matching, Contraction Hierarchies), and observability & analytics (**Pinot** + H3, Gairos) — sourced from Uber, Lyft, DoorDash, OSRM/Valhalla, and Apache Pinot/Flink/Kafka.
- `llm/`  
  How **ChatGPT & Claude** (large language models) work, end to end: next-token prediction & tokenization (**BPE**), the **Transformer** & self-attention (Q/K/V, multi-head, context window), pretraining data pipelines & **scaling laws** (**Chinchilla**), post-training **alignment** — **RLHF** (ChatGPT) vs **Constitutional AI / RLAIF** (Claude), SFT, DPO — and **inference/serving** (decoding, **KV cache**, prefill vs decode, tools/function-calling, **RAG**, safety) — sourced from Stanford **CS229** (Yann Dubois) plus OpenAI, Anthropic, and the foundational papers (Transformer, GPT-3, Chinchilla, InstructGPT, Constitutional AI).

## Topic folders

Each subject lives in its own root-level folder (e.g. `osi/`) and contains both a
summary diagram (`.png`) and detailed markdown notes (`.md`) per topic.

## Goal

Every note should be visual-first: cards, diagrams, icon callouts, and free-flow layout over long prose.