# CDN Edge Computing — Detailed Notes

> Companion deep-dive for the summary diagram: `cdn-edge-compute-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand how CDNs let you run *code* (not just cache bytes) at the edge — the runtimes (Cloudflare Workers, Fastly Compute/VCL, Akamai EdgeWorkers), the request-lifecycle "hook" model, edge state stores, and real use cases including the **virtual waiting room / pre-queue** pattern (the "Walmart pre-check inventory during events" idea).

---

## 1) Why compute at the edge?

Caching answers "serve this *byte* near the user." Edge compute answers "run this *logic* near the user" — before the request ever reaches origin.

- **Lower latency:** logic runs in the PoP the user already hit (330+ cities for Cloudflare, thousands of Akamai PoPs).
- **Offload origin:** auth, routing, personalization, rate-limiting, redirects, A/B tests done at the edge → fewer origin trips.
- **Massive elastic scale:** serverless, autoscaling from zero to millions of requests; no capacity planning.
- **Fast cold starts:** V8 **isolates** (not containers/VMs) → near-zero cold start (Cloudflare "zero cold start"; Akamai < 5 ms).

---

## 2) The three big platforms

| | **Cloudflare Workers** | **Fastly Compute** (+ VCL) | **Akamai EdgeWorkers** |
| --- | --- | --- | --- |
| Runtime | V8 isolates | **WebAssembly** (Wasm) sandbox / VCL FSM | V8 JavaScript engine |
| Languages | JS, TS, Python, Rust, Wasm | Any → Wasm (Rust, JS, Go official) | JavaScript / TypeScript |
| Model | Full request handler | **Compute**: your code owns the whole request; **VCL**: hook-based FSM | Event hooks in request/response |
| State | KV, D1 (SQL), R2 (objects), **Durable Objects**, Queues | Edge data stores, KV, Fanout | **EdgeKV** (distributed KV) |
| Cold start | ~0 (isolates) | Per-request Wasm isolation | < 5 ms |
| Billing | CPU-time based | Requests + compute duration + CPU time | Usage-based |

Two philosophies worth noting:
- **VCL / hook model (Fastly, Varnish, Akamai):** your code is *configuration* injected at specific lifecycle points; the platform drives the request. Great for header/cache/routing tweaks with minimal code.
- **Full-handler model (Workers, Fastly Compute):** your code *is* the app; it explicitly reads the request and makes backend fetches. Great for full apps/APIs at the edge.

---

## 3) The request-lifecycle "hook" model (VCL / EdgeWorkers)

Edge platforms expose **hooks** that fire at specific moments of each HTTP request. You attach logic to a hook instead of writing a top-to-bottom program. VCL runs as a **finite state machine**:

```
vcl_recv    ── client request received (routing, auth, pick backend)
   │  lookup
vcl_hash    ── compute cache key
   ├─ hit  → vcl_hit    → deliver
   ├─ miss → vcl_miss   → vcl_fetch (backend) → vcl_deliver
   └─ pass → vcl_pass   → (bypass cache)
vcl_deliver ── prepare response to client
vcl_log     ── after response sent
```

- `vcl_recv` is where you do **routing, backend selection, access checks (paywalls, tokens), header sanitization**, A/B tests, and origin failover ("pre-flight" pattern via `restart`).
- Akamai **EdgeWorkers** exposes analogous hooks: `onClientRequest`, `onOriginRequest`, `onOriginResponse`, `onClientResponse` (+ response-provider for fully synthetic responses).

> Ordering gotcha (Akamai): EdgeWorkers live in the *delivery* block, so security products (e.g. Bot Manager Premier) may run **after** `onClientRequest`. Always test execution order before production.

---

## 4) Edge state — the hard part

Compute is stateless per-request; real apps need state. Options:

- **KV stores** (Workers KV, EdgeKV): globally replicated, **read at cache speed**, eventually consistent — great for config, feature flags, personalization data.
- **Strongly-consistent coordination — Cloudflare Durable Objects:** a *single addressable instance* per key (per chat room, per document, per game session, per queue) with transactional SQLite + built-in WebSockets. Route all users for a key to the *same* object worldwide → strong consistency without running Redis/queues yourself.
- **SQL / objects:** D1 (serverless SQL), R2 (S3-compatible object storage, zero egress).

**Consistency trade-off:** KV = fast + eventual; Durable Objects = coordinated + strongly consistent (one instance is the bottleneck, by design). Pick per use case.

---

## 5) Edge compute use cases

- **API gateway / routing:** inspect path, add auth headers, route to the right origin — no separate LB.
- **Auth / authorization at the edge:** validate JWT/session/tokens before hitting origin.
- **Personalization & A/B testing:** read `CF-IPCountry`, UA, cookies; return tailored HTML from KV — *no origin hit*.
- **Webhooks & background jobs:** validate + transform + fan-out (with Queues/Cron), dedupe/order with Durable Objects.
- **Content transformation:** image resizing/optimization, HTML rewriting, streaming.
- **Real-time apps:** chat, collaborative editing, multiplayer, live dashboards via Durable Objects + WebSockets.
- **Full-stack apps:** frontend + backend + DB in one Worker (Workers + D1/R2/KV).
- **Waiting room / virtual queue** (next section).

---

## 6) The virtual waiting room / "pre-queue" pattern

This is the pattern behind "run a pre-queue to pre-check inventory during big events" (e.g. flash sales, ticket drops, console launches, Black-Friday-scale retail). **Cloudflare Waiting Room** is the productized version.

**Problem:** legitimate traffic spikes (flash sale, product launch) can overload the origin and crash checkout — losing revenue and trust.

**Solution:** put a queue *at the edge* in front of the protected host/path. When traffic exceeds a threshold, excess users get a branded, on-brand waiting page and are admitted **FIFO / random / lottery** as capacity frees up.

**How it works (edge-native, low latency):**
1. A request to a covered host/path hits a **Waiting Room Worker in the nearest PoP**.
2. The Worker decides **queue vs. let through** using the current **Waiting Room state** — a snapshot of global traffic maintained per data center and continuously updated from worldwide traffic.
3. Each admitted user gets a **cookie**; browsers on the waiting page **auto-refresh (~20 s)** with updated ETA.
4. Slots are allocated to Workers based on the global state; **queueing starts when a Worker's slots run out**. Deciding *at the Worker* means **no significant added latency** (safe to leave on always).
5. **Event scheduling + pre-queue:** teams can schedule cascading events and enable a **pre-queue** (a lobby *before* the sale opens) so early arrivals are ordered fairly before doors open.

```
flash-sale URL ▶ nearest PoP ▶ Waiting Room Worker
                                   │ state says over threshold?
                        ┌──────────┴───────────┐
                        ▼                      ▼
                 send to queue            let through (cookie)
                 (FIFO/random,                │
                  auto-refresh ETA)           ▼
                        └── slot frees ──▶ origin protected
```

**Why the edge is the right place:** the decision happens in the PoP the user already reached, so it adds negligible latency; the origin only ever sees admitted traffic. Distributed global state is the hard part (each PoP works from its own snapshot; counters keep it from queueing too early/late).

**Custom variants:** teams needing exact transactional control (e.g. match release rate to payment-gateway capacity, or *pre-check inventory* before admitting) often build a **custom queue in Workers + Durable Objects** (one Durable Object = the authoritative counter/lock for the drop), which is exactly the "pre-check inventory & other items during events" idea.

---

## 7) End-to-end flow (edge compute request)

```
1. user request → nearest PoP (anycast)
2. TLS terminated at edge
3. security pass (DDoS/WAF/bot) — see notes 03
4. edge function runs (onClientRequest / vcl_recv / Worker fetch)
      ├─ read state: KV / EdgeKV / Durable Object
      ├─ decide: route? auth? personalize? queue? synthesize?
      └─ maybe fetch backend(s) explicitly
5. response assembled at edge (transform / rewrite)
6. onClientResponse / vcl_deliver → user
```

**Risks:** CPU-time limits (e.g. Workers ~10–50 ms CPU) → keep functions lean; KV eventual consistency → don't use for strong invariants (use Durable Objects); test security-vs-compute ordering.

---

## 8) Reliability & operations lens

- **Isolates/Wasm** give fast, safe multi-tenant execution with tiny cold starts.
- **Instant global deploy + rollback:** VCL/Workers compile and push worldwide with no maintenance window; gradual rollouts supported.
- **Autoscale to zero:** pay per request/CPU; no idle cost.
- **What to monitor:** CPU time per invocation, error rate, KV/Durable Object latency & consistency, queue depth / wait-time accuracy (waiting room), backend fetch latency.

---

## 9) Key takeaways

- Edge compute = run **logic** (auth, routing, personalization, transforms, queues) in the PoP, before origin.
- Two models: **hook/FSM** (VCL, EdgeWorkers) for config-style tweaks; **full handler** (Workers, Fastly Compute) for whole apps/APIs.
- **Isolates/Wasm** → near-zero cold start; **CPU-time billing**; autoscale to zero.
- **State** is the hard part: KV/EdgeKV = fast+eventual; **Durable Objects** = coordinated+strong (per-key single instance).
- The **waiting room / pre-queue** is a flagship edge-compute pattern: decide queue-vs-admit at the edge with distributed global state so the origin only sees admitted traffic — and can be customized to **pre-check inventory** during big events.

---

## 10) Quick glossary

- **Isolate:** lightweight V8 sandbox; many per process → cheap, fast cold start.
- **Wasm sandbox:** per-request WebAssembly isolation (Fastly Compute).
- **Hook / lifecycle event:** attach code to a specific request/response stage (`vcl_recv`, `onClientRequest`).
- **KV / EdgeKV:** globally replicated key-value store, eventually consistent.
- **Durable Object:** single strongly-consistent stateful instance addressed by key.
- **Waiting Room / pre-queue:** edge queue that admits users (FIFO/random) to protect origin during surges.

---

## 11) Sources & further reading

**Cloudflare Workers & storage**
- Workers product: <https://workers.cloudflare.com/products/workers/>
- Workers use cases (web apps): <https://developers.cloudflare.com/use-cases/web-apps/>
- Durable Objects: <https://www.cloudflare.com/products/durable-objects/>
- Full-stack on Workers: <https://blog.cloudflare.com/full-stack-development-on-cloudflare-workers/>

**Fastly Compute & VCL**
- Selecting a service type (VCL vs Compute): <https://www.fastly.com/documentation/guides/concepts/services/>
- VCL request lifecycle (hooks/FSM): <https://www.fastly.com/documentation/reference/vcl/request-lifecycle/>
- `vcl_recv` reference (routing/auth): <https://www.fastly.com/documentation/reference/vcl/subroutines/recv/>
- Fastly Compute product: <https://docs.fastly.com/products/compute>
- Varnish — VCL & the FSM: <https://www.varnish-software.com/developers/tutorials/varnish-configuration-language-vcl/>

**Akamai EdgeWorkers**
- Product overview: <https://www.akamai.com/products/serverless-computing-edgeworkers>
- Docs / event model: <https://techdocs.akamai.com/edgeworkers/docs>
- Technical (execution order, hooks): <https://techdocs.akamai.com/edgeworkers/docs/technical>

**Waiting room / pre-queue**
- Cloudflare Waiting Room — About: <https://developers.cloudflare.com/waiting-room/about/>
- Blog — *How Waiting Room makes queueing decisions*: <https://blog.cloudflare.com/how-waiting-room-queues/>
- Blog — *Waiting Room Event Scheduling (pre-queue)*: <https://blog.cloudflare.com/waiting-room-event-scheduling/>
- Product page: <https://www.cloudflare.com/application-services/products/waiting-room/>
