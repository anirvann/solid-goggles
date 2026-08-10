# Kafka Fundamentals & Architecture — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-fundamentals-architecture-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *what Apache Kafka actually is* (a distributed, replicated, append-only commit log — not a "message queue" in the RabbitMQ sense), the physical building blocks (brokers, topics, partitions, offsets, segments, replicas/ISR), how producers and consumer groups move data, and how the cluster stays consistent (controller/KRaft, leader election, high-water mark).

---

## 1) The one-sentence mental model

Kafka is a **distributed append-only log** you can **write to** (produce) and **replay from** (consume) independently, many times, by many readers, with **durability and ordering per partition**.

Think of a topic as a giant notebook split into several columns (partitions). Each write is appended to the end of one column and gets a monotonically increasing line number (**offset**). Readers remember *which line they last read*; they can re-read from any line at any time. Kafka doesn't delete a message when it's read — it deletes by **time/size retention**, so the same event can feed many independent consumers.

Why this matters: a traditional queue (RabbitMQ, SQS) is *destructive read* — a message is consumed once and gone. Kafka is *non-destructive, replayable storage* — which is why it doubles as an event store, a buffer, and a streaming backbone.

---

## 2) Core components (the physical layout)

### Broker
- A single Kafka server process. A **cluster** is a set of brokers (3, 6, 30, …).
- Stores partition data on local disk, serves produce/fetch requests, and participates in replication.
- Each broker has a unique `broker.id`. One broker acts as **controller** (cluster brain).

### Topic
- A named logical stream, e.g. `orders`, `payments.captured`, `driver.location.updates`.
- Purely logical — the real data lives in its **partitions**.

### Partition (the unit of parallelism, ordering, and storage)
- A topic is split into **N partitions** (`orders-0`, `orders-1`, …).
- **Ordering is guaranteed only within a partition**, never across the whole topic.
- Each partition is an ordered, immutable sequence of records; each record gets an **offset** (0,1,2,…) that is unique *within that partition*.
- Partition count sets the **max consumer parallelism** in one group (one partition → at most one consumer in a group).

### Offset
- The position of a record inside a partition. Consumers track "how far I've read" as a **committed offset**.
- **Lag = log-end offset − committed offset** (see note 02).

### Segment + index (on-disk storage)
- A partition is physically a directory of **segment files** (`.log`) plus offset/time indexes (`.index`, `.timeindex`).
- Kafka appends to the **active segment**; when it hits `segment.bytes`/`segment.ms` it rolls a new one. Old segments are deleted (retention) or **compacted**.
- Writes are **sequential appends** → cheap; reads use **zero-copy** (`sendfile`) → the OS page cache does most of the work. This is why Kafka is fast on commodity disks.

### Replica, leader, follower, ISR
- Each partition is replicated `replication.factor` times across brokers.
- One replica is the **leader** (handles all reads/writes); the rest are **followers** that pull to stay in sync.
- **ISR (In-Sync Replicas)** = the set of replicas caught up with the leader. Only ISR members are eligible to become leader.
- **High-water mark (HWM)** = the highest offset replicated to *all* ISR; consumers can only read up to the HWM (so they never read data that could be lost on failover).

### Controller (KRaft vs ZooKeeper)
- The controller manages metadata: which broker leads which partition, ISR changes, broker join/leave, leader elections.
- **Legacy:** metadata lived in **Apache ZooKeeper** (separate ensemble).
- **Modern (KRaft, KIP-500):** Kafka runs its **own Raft-based metadata quorum** — no ZooKeeper. ZooKeeper mode is deprecated (removed in Kafka 4.0). KRaft means faster failover, millions of partitions, one system to operate.

---

## 3) Producers — how data gets in

Key producer mechanics:

1. **Partitioner** decides the target partition:
   - **Key present** → `partition = hash(key) % numPartitions` (default murmur2). Same key → same partition → **ordered per key** (e.g. all events for `order-123`).
   - **No key** → sticky/round-robin batching for throughput.
2. **Batching & compression:** records are buffered per-partition (`batch.size`, `linger.ms`) and compressed (`lz4`/`zstd`/`snappy`/`gzip`) → huge throughput win.
3. **Durability via `acks`:**
   - `acks=0` — fire-and-forget (may lose data).
   - `acks=1` — leader wrote it (can lose data if leader dies before followers copy).
   - `acks=all` — leader **and all ISR** wrote it → strongest durability. Pair with `min.insync.replicas=2` and `replication.factor=3`.
4. **Idempotent producer** (`enable.idempotence=true`, default in modern clients) — dedupes retries so a network retry doesn't create duplicates. Foundation for exactly-once (note 04).

Durability rule of thumb: `replication.factor=3`, `min.insync.replicas=2`, `acks=all` → you can lose 1 broker and still accept writes with no data loss.

---

## 4) Consumers & consumer groups — how data gets out

- A **consumer group** is a set of consumers sharing a `group.id` that **divide the partitions** among themselves; each partition is owned by exactly one consumer *in that group*.
- **Scaling:** add consumers up to the partition count. Beyond that, extra consumers sit idle.
- **Fan-out:** *different* groups each get the *full* stream independently (analytics group + billing group + search-indexer group all read `orders` in parallel — this is Kafka's superpower vs a plain queue).
- **Offset commits:** consumers commit progress to the internal `__consumer_offsets` topic. Auto-commit (`enable.auto.commit`) is easy but risks reprocessing/loss on crash; manual commit after processing gives you control (at-least-once).
- **Rebalancing:** when a consumer joins/leaves or a partition count changes, the **group coordinator** reassigns partitions. Classic rebalances "stop the world"; **cooperative/incremental rebalancing** and **static membership** (`group.instance.id`) reduce the churn (note 06).

### Delivery semantics (preview, full detail in note 04)
- **At-most-once:** commit before processing → may lose on crash.
- **At-least-once (default, most common):** process then commit → may reprocess (make consumers **idempotent**).
- **Exactly-once (EOS):** idempotent producer + transactions + `read_committed` → no dupes, no loss within Kafka-to-Kafka pipelines.

---

## 5) End-to-end flow: one event, produce → replicate → consume

```
① Producer
   record(key="order-123", value=<json>)
   -> partitioner: hash("order-123") % 6 = partition 2
   -> batch + compress -> send to LEADER of orders-2

② Leader broker (say broker 4)
   -> append to active segment of orders-2 (offset = 8000)
   -> followers (brokers 1,5) FETCH and append
   -> once all ISR have offset 8000 -> High-Water Mark advances
   -> with acks=all: ACK returned to producer

③ Storage
   -> data sits in page cache + on disk
   -> retained for retention.ms (e.g. 7 days) OR compacted by key

④ Consumers (independent, replayable)
   group "billing"    reads orders-2 up to HWM, commits offset 8000
   group "analytics"  reads the SAME data at its own pace
   group "search"     can reset to offset 0 and replay history

Failover: if broker 4 dies, controller elects an ISR follower
          (broker 1) as new leader for orders-2 — no data loss
          because acks=all guaranteed it was replicated.
```

---

## 6) Reliability / security / ops lens

- **Reliability:** `RF=3` + `min.insync.replicas=2` + `acks=all`; avoid **unclean leader election** (`unclean.leader.election.enable=false`) so a stale out-of-ISR replica can't be elected and silently drop data. Spread replicas across racks/AZs (`broker.rack`).
- **Ordering caveat:** only per-partition. If you need global order, use 1 partition (kills parallelism) or design keys so the ordering you need lands in one partition.
- **Security:** TLS for in-transit encryption; **SASL** (SCRAM/OAUTHBEARER/Kerberos) for authentication; **ACLs** for authorization per topic/group; encryption-at-rest via disk/volume. mTLS between brokers.
- **Observability (the vitals):** under-replicated partitions (`UnderReplicatedPartitions` must be 0), offline partitions, ISR shrink/expand rate, active controller count (must be exactly 1), request latency, **consumer lag** (note 02), disk usage, page-cache hit rate.
- **Ops:** capacity = partitions × throughput; watch partition count per broker (rebalances get slow with 100k+); use **Cruise Control** for auto-rebalancing; **tiered storage** (KIP-405) offloads old segments to S3 so brokers stay small (note 05).

---

## 7) Key takeaways

- Kafka is a **replayable, distributed commit log**, not a destructive queue — the same event can feed many independent consumer groups.
- **Partition** is the atomic unit of **ordering, parallelism, and storage**; ordering holds *only within a partition* and is keyed by the producer's message key.
- **Offset** = read position; **committed offset** = consumer progress; the gap is **lag**.
- Durability comes from **replication + ISR + `acks=all` + `min.insync.replicas`**, with the **high-water mark** ensuring consumers never read unreplicated data.
- The **controller** (now **KRaft**, ZooKeeper deprecated/removed in 4.0) owns metadata and drives leader election on failure.
- Consumer **groups** split partitions for scale; **different groups** fan out the full stream — this decoupling is the core design win.

---

## 8) Quick glossary

- **Broker:** one Kafka server; a cluster is many brokers.
- **Topic:** named logical stream, split into partitions.
- **Partition:** ordered append-only log; unit of parallelism/ordering.
- **Offset:** position of a record in a partition.
- **Segment:** on-disk file chunk of a partition (+ indexes).
- **Replica / leader / follower:** copies of a partition; leader serves I/O, followers sync.
- **ISR:** in-sync replicas — caught-up copies eligible for leadership.
- **High-water mark (HWM):** highest fully-replicated offset consumers may read.
- **Controller:** cluster brain managing metadata & leader election.
- **KRaft:** Kafka's built-in Raft metadata quorum (replaces ZooKeeper).
- **Consumer group:** consumers sharing a `group.id`, splitting partitions.
- **`acks` / `min.insync.replicas`:** producer durability knobs.
- **Idempotent producer:** dedupes retries to avoid duplicate writes.
- **Log compaction:** retention that keeps the latest value per key.
- **Zero-copy (`sendfile`):** kernel path that makes reads cheap.

---

## 9) Sources & further reading

**Core / official**
- Apache Kafka — *Documentation* (design, replication, producer/consumer configs): <https://kafka.apache.org/documentation/>
- Apache Kafka — *Design section* (log, replication, ISR, delivery semantics): <https://kafka.apache.org/documentation/#design>
- KIP-500 — *Replace ZooKeeper with a self-managed metadata quorum (KRaft)*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum>

**Foundational papers / posts**
- Jay Kreps — *The Log: What every software engineer should know about real-time data's unifying abstraction* (LinkedIn Engineering): <https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying>
- Kreps, Narkhede, Rao — *Kafka: a Distributed Messaging System for Log Processing* (NetDB 2011): <https://www.microsoft.com/en-us/research/wp-content/uploads/2017/09/Kafka.pdf>

**Practical**
- Confluent — *Kafka Internals / storage & replication*: <https://developer.confluent.io/courses/architecture/get-started/>
- Confluent — *KRaft overview*: <https://docs.confluent.io/platform/current/kafka-metadata/kraft.html>
