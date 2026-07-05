# Matching, Dispatch & Routing — Detailed Notes

> Companion deep-dive for the summary diagram: `maps-matching-dispatch-routing-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *how* a platform actually connects **drivers ↔ riders** and **delivery agents ↔ restaurant ↔ customer** — the pipeline from candidate generation → ETA scoring → **batched optimization** (Uber DISCO, DoorDash DeepRed) → offer/accept — and *how* the routing/ETA engine that scores each pair works.

---

## 1) Dispatch is a two-sided marketplace, not a lookup

The naive answer ("assign the nearest driver") is wrong at scale. Dispatch is a **matching** problem on a moving, two-sided market:

- **Ride-hailing:** riders (demand) ↔ drivers (supply). Match in **< 1 second of decision** while vehicles keep moving.
- **Food delivery:** an order has **three** points — restaurant, courier, customer — and prep time, so the courier should arrive *as the food is ready* (dispatch too early → courier idles; too late → food goes cold).

Both are solved with the **same three-stage pipeline**, differing mainly in the cost function.

```
      ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
req → │ 1. Candidate │ → │ 2. ETA /     │ → │ 3. Batched       │ → offer → accept
      │   generation │   │   ML scoring │   │   optimization   │
      │   (H3 k-ring)│   │ (DeepETA/MIP)│   │ (Hungarian/MIP)  │
      └──────────────┘   └──────────────┘   └──────────────────┘
```

---

## 2) Stage 1 — Candidate generation (spatial filter)

- Convert the pickup/restaurant point to an **H3 cell (res 9)** and expand a **k-ring** (`gridDisk`, k≈7 ≈ ~1.3 km) to gather candidate hexes (see note 01).
- Union the in-memory driver/courier sets in those hexes → a **small candidate set** (dozens), filtered by `available` state and constraints (vehicle type, capacity, cash/UPI, EV, etc.).
- **Food delivery adds order-batching candidates:** also collect *other open orders* at the same or nearby restaurants that could be **stacked** onto one courier trip.
- This stage is deliberately **cheap and approximate** — it exists only to avoid running expensive routing over a whole city.

---

## 3) Stage 2 — Scoring each (rider, driver) pair with ETA

You cannot rank candidates by straight-line distance; you need **real travel time on the road network with live traffic**.

### Routing / ETA engine
- A **routing engine** runs shortest-path over the road graph. Production engines (OSRM, Valhalla, Google) don't use plain A*; they use **Contraction Hierarchies (CH)** — see note 04 — to answer a route in **< 1 ms** by exploring ~hundreds of nodes regardless of trip length.
- Live **segment speeds** (from probe data) are pushed into the engine every ~30 s so ETAs reflect current traffic.

### DeepETA (learned correction)
- A pure physics/graph ETA is systematically off (traffic lights, pickup walking, turn penalties). Uber's **DeepETA** is a **hybrid**: the routing engine gives a base ETA, then a deep model (a transformer-style residual) corrects it.
- Runs at **p95 ≈ 4 ms**, served via Uber's **Michelangelo** ML platform at up to **~10M predictions/sec** peak — because it must be called for *every* candidate pair in *every* batch.

### Food-delivery scoring adds more models (DoorDash DeepRed layer 2)
For each `(order, courier)` pair DoorDash runs **four** models:
1. **Prep-time** prediction (when will the food be ready?)
2. **Travel-time** prediction (incl. parking)
3. **Courier acceptance** probability
4. **Variance** estimator (penalize risky/high-variance stacked routes)

The output is a **cost/utility** per edge that the optimizer consumes.

---

## 4) Stage 3 — Batched optimization (the real magic)

### Why batch instead of greedy
Greedy "closest driver first" is locally optimal but globally poor: it can strand a request while grabbing a driver a different request needed more. So platforms **buffer requests for a short window (2–5 s)** and solve the whole batch at once. Uber explicitly contrasts the old "closest first" approach with batched matching that *"considers all open requests and nearby drivers in a market and finds the best overall combination"* — documented **double-digit** utility gains.

### The model: weighted bipartite matching
- Build a **bipartite graph**: riders on one side, candidate drivers on the other; each edge weight = learned **cost** (pickup ETA + driver future earnings + detour + acceptance likelihood + long-term marketplace utility).
- Solve the **assignment problem** to minimize total system-wide cost. Because the LP relaxation of bipartite matching is integral (Edmonds' theorem), the **Hungarian algorithm** solves it exactly in polynomial time.
- **Uber DISCO** (Dispatch Optimization) = this batched bipartite matcher.

### When routes get complex → MIP (DoorDash DeepRed layer 3)
Bipartite/Hungarian only handles one delivery per route. Food delivery needs **stacking** (2+ orders on one trip) and **strategic delay**, so DoorDash uses a **Mixed-Integer Program (MIP)** solved with **Gurobi**. Each window the solver chooses among:
- **single** offer,
- **batched/stacked** offer (Order A at Restaurant X + Order B nearby → one courier),
- **strategic delay** (wait for a better courier about to free up),
- **reassign**.

It maximizes total marketplace utility (speed vs. courier efficiency vs. variance). The Hungarian approach was dropped for large instances because its runtime is too high and it can't express multi-stop routes.

---

## 5) Offer → accept → lock (making the decision atomic)

Once the batch is solved:

1. **Lock** the chosen driver with an atomic state transition (e.g. Redis compare-and-swap `available → offered`) so two batches can't grab the same driver.
2. **Push the offer** to the driver's phone over a persistent stream (Uber **RAMEN**, gRPC bidi — see note 03), typically in **< 100 ms**.
3. Driver has ~**15 s** to accept/decline. On accept → `dispatched`; on decline/timeout → driver returns to the pool and re-enters the next batch.
4. The trip is then run as a **durable workflow** (Uber uses **Cadence**) so a multi-minute, multi-step lifecycle (en-route → arrived → started → completed → paid) survives crashes and retries.

---

## 6) End-to-end dispatch flow (ride-hailing happy path)

```
1. Rider taps "Book"                         -> Ride Service creates request
2. Request buffered into the 2-5s batch window
3. Candidate gen: H3 k-ring around pickup    -> dozens of nearby available drivers
4. For each (rider, driver): DeepETA score   -> edge weights (ETA + utility)
5. DISCO builds bipartite graph, Hungarian solve -> global optimal assignment
6. Lock driver (atomic CAS available->offered)
7. RAMEN push offer to driver phone (<100ms)
8. Driver accepts within 15s                 -> state = DISPATCHED
9. Live location stream starts: driver position pushed to rider app (note 03)
10. Cadence workflow drives trip lifecycle -> ... -> completed -> payment
```

Food delivery is the same skeleton with a 3-point route, prep-time gating, stacking, and MIP instead of Hungarian.

---

## 7) Surge / dynamic pricing (the marketplace balancer)

- When demand > supply in an **H3 res-7** cell, a **surge multiplier** raises price to ration demand and pull in drivers.
- Computed in near-real-time from streaming demand/supply per hexagon (Uber's **Gairos** / streaming platform — see note 05).
- It's the feedback loop that keeps the two-sided market from collapsing during spikes; it also feeds back into dispatch edge weights (driver future-earnings term).

---

## 8) Reliability / security / ops lens

- **Reliability:** every offer must be **idempotent + atomically locked** — a double-assigned driver is a customer-visible failure. Timeouts must always return supply to the pool. The trip workflow (Cadence) guarantees the long lifecycle completes exactly once despite crashes.
- **Latency budget:** candidate gen (µs) + ETA (single-digit ms × candidates) + batch window (2–5 s intentional) + push (<100 ms). The batch window is *deliberate* latency traded for global quality.
- **Fairness/quality:** guard against starving drivers of offers, cherry-picking, and stacking that hurts one customer's ETA; DoorDash's variance model exists precisely to penalize risky stacks.
- **Observability:** track match rate, time-to-match, offer accept rate, ETA error (predicted vs. actual), cancellations, and unfulfilled-request rate.

---

## 9) Key takeaways

- Dispatch = **candidate generation (H3) → ETA/ML scoring → batched optimization → offer/accept**, not "nearest driver."
- **Batching (2–5 s) + bipartite matching (Hungarian)** beats greedy globally — Uber's **DISCO**; documented double-digit gains.
- **ETA must be road-network + learned:** DeepETA (physics + ML) at p95 ≈ 4 ms feeds the edge weights.
- Food delivery adds **prep-time, stacking, and strategic delay**, so DoorDash's **DeepRed** uses a **MIP (Gurobi)**, not plain Hungarian.
- Assignment must be **atomically locked** (CAS) and pushed in <100 ms; the trip runs as a **durable workflow**.
- **Surge pricing** (per H3 hexagon) is the feedback loop balancing the two-sided market.

---

## 10) Quick glossary

- **DISCO:** Uber's Dispatch Optimization — batched bipartite matcher.
- **DeepRed:** DoorDash's dispatch engine (candidate → ML scoring → MIP).
- **Bipartite matching:** pairing two disjoint sets (riders/drivers) to minimize total cost.
- **Hungarian algorithm:** polynomial exact solver for the assignment problem.
- **MIP / Gurobi:** Mixed-Integer Program / a commercial solver, used for stacking + delay.
- **DeepETA:** Uber's hybrid physics+ML travel-time predictor.
- **Michelangelo:** Uber's ML platform serving models like DeepETA at scale.
- **k-ring (`gridDisk`):** H3 cell + surrounding cells within distance k (candidate set).
- **Surge multiplier:** dynamic price factor per hexagon when demand > supply.
- **Cadence:** Uber's durable workflow engine for the trip lifecycle.

---

## 11) Sources & further reading

**Ride-hailing dispatch**
- Uber Marketplace — batched matching vs. "closest first": <https://www.uber.com/us/en/marketplace/matching/>
- Uber Engineering — *DeepETA: how Uber predicts arrival times with deep learning*: <https://www.uber.com/blog/deepeta-how-uber-predicts-arrival-times/>
- Uber Engineering — *Michelangelo ML platform*: <https://www.uber.com/blog/michelangelo-machine-learning-platform/>
- Sujeet Jaiswal — *Design Uber-style ride hailing (H3 + DISCO + DeepETA, grounded in Uber's published work)*: <https://sujeet.pro/articles/design-uber-ride-hailing>
- The HLD Handbook — *Design a ride-hailing service (batched bipartite matching, Cadence)*: <https://hld.handbook.academy/curriculum/case-studies/ride-hailing/>

**Food-delivery dispatch**
- DoorDash Engineering — *Using ML and optimization to solve DoorDash's dispatch problem (DeepRed)*: <https://careersatdoordash.com/blog/using-ml-and-optimization-to-solve-doordashs-dispatch-problem/>
- DoorDash Engineering — *Next-generation optimization for Dasher dispatch (beyond Hungarian → routes)*: <https://careersatdoordash.com/blog/next-generation-optimization-for-dasher-dispatch-at-doordash/>
- DoorDash Engineering — *Iterating real-time assignment algorithms through experimentation*: <https://doordash.engineering/2020/12/08/optimizing-real-time-algorithms-experimentation/>
- The HLD Handbook — *Design a food-delivery service (DeepRed's three layers, stacking)*: <https://hld.handbook.academy/curriculum/case-studies/food-delivery/>
