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
- `kafka/`  
  Apache **Kafka**, the distributed replayable commit log: fundamentals & architecture (brokers/topics/**partitions**/offsets, replication/**ISR**/high-water mark, **KRaft**), **consumer lag** (detection, real-world effects, and handling with DLTs/retry topics/**KEDA**), use cases & real-life examples (**CDC**, event sourcing, LinkedIn/Uber/Netflix/NYT), delivery semantics/ordering/**exactly-once** (idempotent producer + transactions), the ecosystem (**Connect**, **Streams/ksqlDB/Flink**, **Schema Registry**, tiered storage), and operations/scaling/reliability — sourced from the Apache Kafka docs/KIPs and Confluent.

## Topic folders

Each subject lives in its own root-level folder (e.g. `osi/`) and contains both a
summary diagram (`.png`) and detailed markdown notes (`.md`) per topic.

## Goal

Every note should be visual-first: cards, diagrams, icon callouts, and free-flow layout over long prose.