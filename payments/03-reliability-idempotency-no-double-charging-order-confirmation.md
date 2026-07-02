# Reliability: Idempotency, No Double-Charging & Order Confirmation — Detailed Notes

> Companion deep-dive for the summary diagram: `payments-reliability-idempotency-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the distributed-systems core of payments — why **exactly-once is impossible**, how **idempotency keys** give you "effectively exactly-once", how **at-least-once webhooks + reconciliation** guarantee correct order confirmation, and how to **never double-charge** a customer.

---

## 1) The core problem: the ambiguous failure

You call the charge API. The connection drops before the response arrives. **Did the charge happen or not?** You cannot tell. This is the *ambiguous failure*, and it is the root of nearly every payment reliability bug.

- If you **retry** and it *did* succeed → **double charge**.
- If you **don't retry** and it *didn't* succeed → **lost payment / unpaid order**.

Foundational truth (Stripe, Kafka, distributed-systems theory all agree): **exactly-once *delivery* over an unreliable network is impossible.** The sender can't distinguish a lost request from a lost response. What you actually build is **at-least-once delivery + idempotent processing = "effectively exactly-once."**

---

## 2) Idempotency keys — the single most valuable pattern

**Idempotent** = calling an operation many times with the same input produces the same result and the side effect happens **once**.

### How it works (the Stripe model)
1. Client generates a **unique key per logical operation** (UUIDv4 / ULID) and sends it in the `Idempotency-Key` header on the mutating `POST`.
2. Server stores `(key, request fingerprint, response, status)`.
3. On a retry with the same key, the server **replays the stored response** instead of re-executing → customer charged **once**.

```
client                         server
  │  POST /charge  Idempotency-Key: k1   │
  ├─────────────────────────────────────▶│  first time: execute, store (k1 → resp)
  │            (response lost)            │
  ├──── retry same k1 ───────────────────▶│  seen k1: replay stored resp (no new charge)
  ◀───────────── same response ──────────┤
```

### The rules that matter (from Stripe's API + engineering blog)
- **Save the outcome regardless of success/failure.** A retried `400`/`500` replays the same result. To recover from a `4xx` validation error, mint a **new** key.
- **Retention window:** Stripe keeps keys **~24 hours**, bounding storage.
- **Uniqueness scope:** typically `(user_id/merchant_id, idempotency_key)` so two callers can reuse a value without collision.
- **Conflict = 409:** a *different* payload with the *same* key should be rejected (mismatched request fingerprint).
- **Deterministic downstream keys:** when calling banks/networks, derive a **child key** from the parent (e.g. `stripe-charge-{key}`) so the *external* system also dedups.
- **Deterministic keys from business identity:** Razorpay's guidance — make the key deterministic from `orderId + sequence` so a natural retry reuses the same key automatically.

> Real-world impact (public Stripe SRE talk): ~95% of write requests carry an idempotency key; during a 2021 AWS network blip, idempotency prevented ~30M duplicate charges. Keys fit in a single Redis cluster at Stripe scale.

### Correct storage / atomicity
The store step must be **atomic** so two concurrent retries can't both execute:

```sql
-- Postgres: unique constraint on the key; only one insert wins
INSERT INTO idempotency_keys (key, merchant_id, request_hash, status)
VALUES ($1, $2, $3, 'in_progress')
ON CONFLICT (merchant_id, key) DO NOTHING;   -- loser reads the winner's row
```

Use `SETNX` (Redis) or a conditional write (DynamoDB) for the same "exactly one writer" guarantee, and a TTL to auto-expire.

### Recovery points (multi-step operations)
A single charge often spans steps (create customer → reserve inventory → call bank → write ledger). Store a **recovery point** per phase so that after a crash you **resume from the last completed phase** rather than redoing everything — the idempotency record becomes a mini state machine.

---

## 3) Webhooks: at-least-once, so make handlers idempotent

Payment status is **asynchronous**: the truth arrives via a **webhook** (`payment.captured`, `payment.failed`, `refund.processed`). Gateways guarantee **at-least-once** delivery with retries and backoff — so **you will receive duplicates and out-of-order events.**

Two non-negotiables (Stripe, Razorpay, PayU all say this):

1. **Verify the signature.** Webhooks carry an **HMAC signature** (e.g. Stripe `Stripe-Signature`, Razorpay `X-Razorpay-Signature`) computed with a shared secret. Reject anything that doesn't verify — otherwise anyone can POST "you got paid".
2. **Deduplicate + idempotent apply.** Persist a `webhook_events` table keyed by the provider's **event id**; if already processed, ack and no-op.

```
receive event ─▶ verify HMAC ──fail──▶ 401 (drop)
                   │ ok
                   ▼
        INSERT event_id  ──conflict──▶ already handled → 200 (no-op)
                   │ new
                   ▼
        apply state transition (atomic) ─▶ 200 ack
```

- **Ack fast, process async.** Return `2xx` quickly; do heavy work off a queue (Razorpay's notification service uses a stream + workers + per-customer QoS, degrading priority for slow endpoints). Slow acks cause the provider to retry → more duplicates.
- **Order confirmation source of truth = verified webhook (or server-side status fetch), never the browser redirect.** Redirects are lost when users close the tab; webhooks are retried.

---

## 4) No double-charging — layered defense

Duplicates come from *many* places; defend at each layer:

| Source of duplicate | Defense |
| --- | --- |
| User double-clicks **Pay** | Disable button + client-generated idempotency key per checkout attempt |
| Client auto-retry on timeout | Same `Idempotency-Key` on retries |
| Backend/worker retry after crash | **Deterministic** key from `orderId+seq`; queue redelivery reuses key |
| Gateway sends webhook twice | `event_id` dedup table |
| Two acquirer routes attempted | Shared logical intent + idempotency at the PSP |
| Concurrent requests, same key | Atomic `INSERT … ON CONFLICT` / `SETNX` |

Pattern that ties it together (Stripe dot-dev reference architecture): frontend → backend **enqueues** a payment job with a UUID idempotency key → **worker** calls the gateway with that key in the header → if the worker crashes / gets a transient error, the message returns to the queue and the **retry reuses the same key**, so only **one** PaymentIntent is ever created.

---

## 5) Cross-service consistency: the transactional outbox

In microservices you must update **your DB** *and* **notify another service / publish an event** atomically. A crash between the two = inconsistency (e.g. payment saved but inventory never told). You **cannot** wrap a DB write and a network call in one transaction.

**Transactional outbox** (Razorpay's public pattern, "Outboxer"):
1. In the **same local DB transaction**, write the business row **and** insert a task/event into an `outbox` table.
2. A separate **relay/processor** reads unprocessed outbox rows and publishes them (to Kafka/Kinesis/queue) with retries/backoff.
3. **Consumers must be idempotent** because the relay is at-least-once (replays failed tasks).

```
BEGIN
  UPDATE payments SET status='captured' WHERE id=...;
  INSERT INTO outbox (event='payment.captured', payload=...);
COMMIT
        │ (async relay)
        ▼
  publish → inventory / ledger / notification (idempotent consumers)
```

This gives "read-your-own-writes" locally + reliable cross-service propagation in an **eventually consistent** way — which is exactly how Razorpay reconciles payment/order/inventory state.

---

## 6) Distributed transactions & the Saga / state machine

A payment spanning multiple services (or multiple payment methods) is a **saga**: a sequence of local transactions, each with a **compensating action** if a later step fails.

- **Payment orchestrator** owns the state machine, sequences steps, and guarantees **exactly-once** semantics even with retries (Razorpay LinkedPayments).
- On failure of a later leg → **compensate** (void/reverse earlier authorizations). Example: gift card debited but card auth fails → **auto-reverse** the gift card, do **not** mark the order paid.
- Withhold "success" side effects (the "authorized" webhook, the confirmation email) until **all** legs succeed.

State transitions must be **atomic DB operations** on a well-defined machine (see the order state machine in note 01).

---

## 7) Reconciliation — the safety net that catches everything

Even with idempotency + webhooks, events get lost, workers die, providers have incidents. **Reconciliation** is the periodic truth-repair:

1. **Fetch authoritative status** from the PSP (settlement/report files or status API) for a time window.
2. **Diff** against your ledger/order DB.
3. **Repair breaks:** money-moved-but-order-unpaid (orphaned order) → fulfill; order-paid-but-no-money → investigate/refund; refunds/chargebacks → post to ledger.

Design the ledger as **double-entry** and immutable (append-only postings) so reconciliation is a clean diff, and settlements always balance. Razorpay reconciles across microservices for settlements (including T+0 prioritization) and runs **chaos testing** to validate consistency under failure.

**What to monitor:** idempotency-key hit ratio (aim >90% → clients are sending keys), webhook delivery/dedup rate, reconciliation **break count & age**, orphaned-order count, ledger imbalance = 0 invariant.

---

## 8) Key takeaways

- **Exactly-once delivery is impossible**; build **at-least-once + idempotent processing** = effectively exactly-once.
- **Idempotency keys** (client-generated, atomically stored, ~24h retained, replay stored response) are the primary defense against double-charging.
- **Webhooks are at-least-once** → always **verify HMAC** and **dedup by event id**; the verified webhook (not the redirect) confirms the order.
- Use the **transactional outbox** for atomic DB-write + event-publish; consumers must be idempotent.
- Multi-step/multi-method payments are **sagas** with compensations; withhold success until all legs pass.
- **Reconciliation** against PSP truth is the final safety net that catches orphaned orders and ledger breaks.

---

## 9) Quick glossary

- **Ambiguous failure:** lost response — you can't tell if the op succeeded.
- **Idempotency key:** unique per-operation token enabling safe retries.
- **Effectively exactly-once:** at-least-once delivery + idempotent apply.
- **HMAC signature:** keyed hash proving webhook authenticity.
- **Outbox pattern:** write event to a DB table in the same txn; relay publishes it.
- **Saga / compensation:** distributed transaction via local steps + undo actions.
- **Orphaned order:** customer charged but order shows unpaid.
- **Reconciliation:** diff local state against PSP truth and repair.

---

## 10) Sources & further reading

**Idempotency (canonical)**
- Stripe Engineering — *Designing robust and predictable APIs with idempotency*: <https://stripe.com/blog/idempotency>
- Stripe API — *Idempotent requests*: <https://docs.stripe.com/api/idempotent_requests>
- Stripe Dot Dev — *Because nobody likes being charged twice*: <https://stripe.dev/blog/because-nobody-likes-being-charged-twice>
- The HLD Handbook — *Idempotency & exactly-once: the honest truth*: <https://hld.handbook.academy/curriculum/distributed-systems-theory/idempotency-exactly-once/>

**Webhooks / delivery**
- Stripe — *Webhooks & signature verification*: <https://docs.stripe.com/webhooks>
- Razorpay — *Webhooks* docs: <https://razorpay.com/docs/webhooks/>
- Razorpay Engineering — *How Razorpay's notification service handles increasing load*: <https://engineering.razorpay.com/how-razorpays-notification-service-handles-increasing-load-f787623a490f>

**Outbox / consistency / orchestration**
- Razorpay Engineering — *Atomic dual writes via Outboxer*: <https://engineering.razorpay.com/achieving-reliable-dual-writes-in-distributed-systems-cb9ff3b9bfc1>
- Razorpay Engineering — *LinkedPayments (orchestrator, exactly-once, compensation)*: <https://dev.to/razorpaytech/linkedpayments-building-payment-chains-in-a-microservices-architecture-43ca>
- microservices.io — *Transactional outbox pattern*: <https://microservices.io/patterns/data/transactional-outbox.html>
- microservices.io — *Saga pattern*: <https://microservices.io/patterns/data/saga.html>
