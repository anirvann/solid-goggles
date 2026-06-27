# System Design Visual Note Template

Use this template when creating a new topic.

---

## [Series Marker] [Topic Title]

**Learning goal:**  
Explain what the system does, how requests flow through it, and what trade-offs matter in production.

### 1) Big picture panel

- **What it is:**  
- **Where it fits:**  
- **Core components:**  

Visual:
- One architecture snapshot with labeled components.

### 2) Component cards (repeat per component)

#### [Component Name]

- Role:
- Inputs/Outputs:
- Failure mode:
- Observability signal:

Visual:
- Icon + short card + 1 connector to related component.

### 3) End-to-end flow (mandatory)

Create a left-to-right flow strip:

`Client -> Edge -> Service -> Data -> Response`

For each step, include:
- Action
- Decision point
- One risk

### 4) Scaling + reliability panel

- Bottlenecks
- Horizontal/vertical scaling choices
- Caching strategy
- Queue/retry/circuit-breaker considerations

Visual:
- Mini "before vs after scale" comparison.

### 5) Security + data panel

- AuthN/AuthZ boundary
- Data classification
- Encryption at rest/in transit
- Secret management

Visual:
- Trust boundary sketch.

### 6) Operations checklist

- SLOs defined
- Dashboards in place
- Alerts configured
- Runbooks available
- Backup/restore tested
- Cost guardrails defined

### 7) Key takeaways (3-7 bullets)

-  
-  
-  

### 8) Quick glossary

- [Term 1]:
- [Term 2]:
- [Term 3]:

---

## Visual quality checklist (must pass)

- [ ] Visuals are primary; prose is concise.
- [ ] Section cards are clearly separated and color-coded.
- [ ] At least one end-to-end sequence flow is included.
- [ ] Components and arrows are consistently labeled.
- [ ] Final recap gives implementation-ready understanding.
