# Kafka Delivery Semantics, Ordering & Exactly-Once — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-delivery-semantics-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the three delivery guarantees (at-most-once, at-least-once, exactly-once), *why duplicates and reordering happen*, how the **idempotent producer** and **transactions** deliver **exactly-once semantics (EOS)**, and the practical rules for **preserving ordering**.

Cross-links: producers/consumers & offsets → note 01; idempotent consumers as a lag-recovery safety net → note 02.

---

## 1) The three delivery semantics

| Guarantee | How you get it | Risk | Use when |
| --- | --- | --- | --- |
| **At-most-once** | commit offset **before** processing | **lost** messages on crash | metrics you can drop |
| **At-least-once** *(default & most common)* | process **then** commit; producer retries | **duplicates** | almost everything (make it idempotent) |
| **Exactly-once (EOS)** | idempotent producer + transactions + `read_committed` | complexity/overhead | money, dedup-critical, stream processing |

Reality check: **at-least-once is the workhorse.** Most systems choose it and make downstream effects **idempotent** (dedupe by key/id) rather than paying the full EOS cost.

---

## 2) Why duplicates happen (and how idempotence fixes it)

A producer sends a record, the broker writes it, but the **ACK is lost** on the network. The producer **retries** → the same record is written twice.

**Idempotent producer** (`enable.idempotence=true`, default in modern clients):
- Each producer gets a **Producer ID (PID)** and attaches a **monotonic sequence number per partition**.
- The broker remembers the last sequence per (PID, partition) and **drops duplicates** whose sequence it has already seen.
- Result: **no duplicates from producer retries**, and it also **prevents reordering on retry** (see §4). Requires `acks=all`, `retries>0`, `max.in.flight.requests.per.connection<=5`.

Idempotence solves *producer-side* dupes only. End-to-end EOS needs transactions.

---

## 3) Exactly-once semantics (EOS) — transactions

EOS matters most for **consume → process → produce** pipelines (Kafka Streams, or any read-then-write app). Without it, a crash between "produced output" and "committed input offset" causes reprocessing → duplicate output.

**Kafka transactions** make the output write **and** the input-offset commit **atomic**:

```
producer.initTransactions()          // once, with a transactional.id
while (true) {
  records = consumer.poll()
  producer.beginTransaction()
  for r in records:
     producer.send(transform(r))                 // output topic(s)
  producer.sendOffsetsToTransaction(offsets,     // input offsets, in the SAME txn
                                    consumerGroupMetadata)
  producer.commitTransaction()       // output + offsets commit atomically (or abort)
}
```

- Consumers reading the output set **`isolation.level=read_committed`** so they see only **committed** transactional messages (aborted/in-flight records are invisible).
- A **transaction coordinator** + a `__transaction_state` log and **transaction markers** (commit/abort) in the partitions make this atomic.
- **Kafka Streams**: set `processing.guarantee=exactly_once_v2` and it wires all of this for you (EOS v2 is more efficient — one producer per instance instead of per task).

**Scope & caveat:** EOS is exactly-once **within Kafka** (Kafka→process→Kafka). Effects on **external systems** (a DB write, an email) are only exactly-once if that sink is **idempotent** or participates in the same transaction. So even with EOS, design external side-effects to be idempotent (upsert by key, dedupe table).

---

## 4) Ordering — the rules

- **Guaranteed only within a partition.** Cross-partition/topic order is not guaranteed.
- **Same key → same partition → ordered.** Choose the partition **key** to be the entity whose order you care about (e.g. `orderId`, `accountId`).
- **Retries can reorder** if `max.in.flight.requests.per.connection > 1` and idempotence is **off**: batch 2 could land before a retried batch 1. **Idempotent producer prevents this** even with in-flight up to 5.
- **Adding partitions changes key→partition mapping** for new records → can break the per-key order for a key that moves partitions. Over-provision partitions to avoid mid-life repartitioning.
- **Consumer-side:** within a partition you get records in offset order; if you process a partition's records with a **thread pool**, you can reorder them yourself — keep per-key/per-partition processing sequential where order matters.

---

## 5) End-to-end: a payment processed exactly once

```
[ payments.requested ]  (key = paymentId)
        │  read_committed consumer
        ▼
  Payment processor (transactional.id = "pay-proc-1")
   beginTransaction
     charge = call PSP  (idempotency-key = paymentId)  // external, idempotent
     send( payments.captured, paymentId, result )       // output topic
     sendOffsetsToTransaction( payments.requested offset ) // input offset
   commitTransaction         // output + offset atomic
        │
        ▼
[ payments.captured ]  --> ledger/settlement consumers (read_committed)

Crash mid-way -> transaction ABORTS -> no captured event, no offset commit
             -> on restart the same input is reprocessed, PSP idempotency-key
                dedupes the charge -> no double charge.
```

This combines **Kafka EOS** (atomic output+offset) with an **idempotent external call** (PSP idempotency key) — the correct pattern for money.

---

## 6) Reliability / security / ops lens

- **Reliability:** default to **at-least-once + idempotent consumers**; reserve **EOS** for money/dedup-critical or Streams pipelines (it adds latency & coordinator load). Always `acks=all` + `min.insync.replicas=2` + idempotent producer for durability.
- **Ordering:** pick keys deliberately; keep `enable.idempotence=true` so retries don't reorder; avoid live repartitioning of order-sensitive topics.
- **Security:** transactional IDs are authz-scoped — use ACLs so a rogue client can't fence others' transactions.
- **Observability:** monitor transaction abort rate, `transactional.id` expiry, producer retry rate, and duplicate-detection metrics; a rising abort rate signals coordinator or timeout issues.

---

## 7) Key takeaways

- Three guarantees: **at-most-once** (may lose), **at-least-once** (may dup — the common default), **exactly-once** (no dup/loss within Kafka).
- **Idempotent producer** (PID + per-partition sequence) removes **producer-retry duplicates** and prevents retry-reordering — it's on by default now.
- **Transactions** make **output writes + input-offset commit atomic**; consumers must read with **`read_committed`**. Kafka Streams turns this on via `exactly_once_v2`.
- **EOS is Kafka-scoped**; external side-effects still need to be **idempotent** (idempotency keys, upserts).
- **Ordering is per-partition, keyed by the message key**; don't repartition order-sensitive topics mid-life.

---

## 8) Quick glossary

- **At-most/at-least/exactly-once:** the three delivery guarantees.
- **Idempotent producer:** dedupes retries via PID + sequence number.
- **PID:** producer id assigned by the broker.
- **Transaction / `transactional.id`:** atomic multi-partition write + offset commit.
- **Transaction coordinator / markers:** broker component + commit/abort records enabling atomicity.
- **`read_committed`:** consumer isolation level that hides aborted/in-flight txn records.
- **`exactly_once_v2`:** Kafka Streams EOS processing guarantee.
- **Idempotency key:** external-system dedupe key (e.g. for a payment API).
- **`max.in.flight.requests.per.connection`:** unacked requests per connection (affects reordering).

---

## 9) Sources & further reading

- Apache Kafka — *Design: message delivery semantics*: <https://kafka.apache.org/documentation/#semantics>
- Confluent — *Exactly-once semantics in Apache Kafka (idempotent producer + transactions)*: <https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/>
- KIP-98 — *Exactly-once delivery and transactional messaging*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-98+-+Exactly+Once+Delivery+and+Transactional+Messaging>
- KIP-447 — *Producer scalability for exactly-once (EOS v2)*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-447%3A+Producer+scalability+for+exactly+once+semantics>
- Confluent — *Transactions & processing guarantees in Kafka Streams*: <https://docs.confluent.io/platform/current/streams/concepts.html#processing-guarantees>
