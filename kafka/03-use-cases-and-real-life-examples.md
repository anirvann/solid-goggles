# Kafka Use Cases & Real-Life Examples — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-use-cases-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** See *the full range of what Kafka is used for* beyond "message queue" — messaging, activity tracking, log/metrics aggregation, stream processing, event sourcing, CDC, the storage/commit-log role — and ground each pattern in *how real companies actually use it* (LinkedIn, Uber, Netflix, Pinterest, banks, retail).

Cross-links: fundamentals → note 01; the streams/connect ecosystem that powers many of these → note 05.

---

## 1) The six canonical use-case patterns

Kafka's docs frame it as an **event streaming platform**; in practice usage clusters into six patterns:

### 1. Messaging / decoupling (pub-sub backbone)
Replace point-to-point service calls with events. Producers don't know consumers; add a new consumer without touching producers.
- *Why Kafka over RabbitMQ/SQS here:* replay, multiple independent consumer groups, high throughput, retention.
- *Example:* an `order.placed` event consumed independently by inventory, notifications, analytics, and fraud.

### 2. Website / activity tracking (the original use case)
Every page view, click, search, and impression → a topic. This is **why LinkedIn built Kafka** (2010): a high-volume feed of user activity events fanning out to real-time monitoring, dashboards, and offline (Hadoop) load.

### 3. Log & metrics aggregation
Collect logs/metrics from thousands of hosts into topics, then ship to Elasticsearch/Splunk/Pinot/S3. Kafka is the durable buffer that absorbs bursts so the storage tier isn't overwhelmed.

### 4. Stream processing
Transform/enrich/aggregate streams in flight with **Kafka Streams**, **ksqlDB**, **Apache Flink**, or **Spark Streaming** (note 05). Windowed aggregations, joins, real-time features. Output back to Kafka for the next stage.

### 5. Event sourcing
Model state changes as an **ordered, immutable log of events** — Kafka *is* the source of truth; current state is a projection you rebuild by replaying. Log **compaction** keeps the latest value per key so you can restore state.

### 6. Commit log / storage & data integration
Kafka as the **central nervous system / "source of truth" bus** between systems, and as durable storage (retention + tiered storage). Combined with **Kafka Connect + CDC** it becomes the integration layer moving data between DBs, warehouses, search, and caches.

---

## 2) "What *other* uses does Kafka have?" (beyond the obvious queue)

People first meet Kafka as a queue. The less-obvious, high-value uses:

- **Change Data Capture (CDC):** stream a database's change log (via **Debezium**) into Kafka → downstream search indexes, caches, data lakes stay in sync without dual-writes. Solves the dual-write/consistency problem.
- **Database materialized views / read models:** build query-optimized projections (CQRS) by consuming events.
- **Cache invalidation:** emit an event on write; a consumer busts the relevant cache keys (avoids stale reads — see lag caveat in note 02).
- **Saga / workflow orchestration:** coordinate long-running distributed transactions across microservices via events (compensating actions on failure).
- **Outbox pattern:** write DB row + outbox event in one transaction, then relay the outbox to Kafka (via CDC) → atomic "update DB and publish event".
- **Real-time ML feature pipelines / feature stores:** compute online features from event streams (Flink/Kafka Streams) for fraud, recommendations, ranking.
- **IoT / telemetry ingestion:** millions of device/sensor/vehicle events per second (connected cars, smart meters).
- **Metrics/observability backbone:** the transport under monitoring pipelines.
- **Data lake / warehouse ingestion:** Connect sinks to S3/HDFS/Snowflake/BigQuery for batch + streaming ETL (the "Kappa architecture" — one streaming path instead of separate batch + speed layers).
- **Bridging to other systems:** MQTT bridges, replication across regions/DCs (MirrorMaker 2, uReplicator), and as the buffer in front of slow sinks.

---

## 3) Real-life company examples (documented)

| Company | What they run on Kafka | Scale / note |
| --- | --- | --- |
| **LinkedIn** (creator) | activity tracking, metrics, messaging, stream processing; **Samza** stream jobs | **~7 trillion messages/day** across thousands of brokers (publicly cited); Kafka was born here, donated to Apache 2011 |
| **Uber** | location pings, dispatch, surge, ETA, Kafka-based analytics (Gairos); **uReplicator** for cross-DC | **trillions of messages / multiple PB per day**; one of the largest deployments |
| **Netflix** | **Keystone** data pipeline — events → stream processing → analytics/personalization; also uses Flink | **trillions of events/day**, PB-scale ingestion on Kafka |
| **Pinterest** | real-time ads budgeting, experiment metrics, ML feature pipelines | thousands of brokers; heavy Kafka + Flink usage |
| **Shopify / retail** | order events, inventory, buyer activity, flash-sale buffering | absorb spiky sale traffic without dropping events |
| **Banks / fintech (e.g. major payment networks, ING, Goldman)** | payments, fraud detection streams, audit/event sourcing, CDC to data platforms | strong-durability config (`acks=all`, RF=3), exactly-once for money movement |
| **The New York Times** | **entire published-content history stored in a single Kafka log** (source of truth) used to feed every downstream app | classic event-sourcing / log-as-storage case study |
| **Slack / Robinhood / Datadog / Twitter (X)** | messaging backbone, metrics, event pipelines, alerting | large multi-cluster deployments |

> Adoption footprint often cited: a large majority of the Fortune 100 use Kafka in some form.

---

## 4) Concrete worked example: e-commerce order lifecycle

Ties patterns 1–6 together in one system (see also `payments/`).

```
Checkout ──produce──> [ orders ] topic (key = orderId, RF=3, acks=all)
                          │
     ┌────────────────────┼───────────────────────┬──────────────────┐
     ▼                    ▼                         ▼                  ▼
 Inventory svc       Payments svc              Notifications      Analytics/ML
 (reserve stock)     (auth+capture ->          (email/SMS/push)   (Flink -> Pinot
     │                payments.captured)            │              dashboards)
     ▼                    │                         ▼
 stock.reserved           ▼                    order.confirmed
 (compacted, current   Fraud model (Flink)          │
  stock per SKU)        scores stream               ▼
     │                    │                     Search indexer
     ▼                    ▼                     (Connect -> Elastic)
 Cache invalidation   ledger/settlement
 consumer (bust SKU)  (event-sourced)

CDC: MySQL binlog --Debezium--> [ db.changes ] --> data lake (S3/Snowflake)
```

Every box is an **independent consumer group** reading the same durable events at its own pace — add a new capability by adding a consumer, never by modifying checkout.

---

## 5) When *not* to use Kafka (so the picture is honest)

- **Low-throughput task queue with per-message ack/priority/delay:** RabbitMQ / SQS is simpler; Kafka has no per-message ack or native priority.
- **Request/response RPC:** use gRPC/HTTP — Kafka is one-way, async.
- **Tiny apps / few events per second:** operational overhead isn't worth it; a DB table or managed queue is enough.
- **Very large payloads (video/files):** store the blob in object storage, put a *reference* on Kafka.
- **Strict global ordering across everything:** Kafka only orders per partition.

---

## 6) Reliability / security / ops lens

- **Reliability:** for money/critical flows use `acks=all`, `RF=3`, `min.insync.replicas=2`, idempotent/transactional producers (note 04). For droppable telemetry, cheaper settings are fine.
- **Multi-region:** replicate with **MirrorMaker 2** / cluster linking for DR and geo-locality; decide active-active vs active-passive.
- **Security:** TLS + SASL + ACLs per topic; be careful CDC/activity topics carry PII — govern with a **Schema Registry** and access controls (note 05).
- **Cost/ops:** retention + **tiered storage** (offload old segments to S3) keeps the log "infinite" without giant brokers; right-size partitions per use case.

---

## 7) Key takeaways

- Kafka spans **six patterns**: messaging, activity tracking, log/metrics aggregation, stream processing, event sourcing, and commit-log storage/integration.
- Its **non-obvious** power uses are **CDC, outbox, cache invalidation, sagas, feature pipelines, IoT ingestion, and data-lake integration** — it's a data backbone, not just a queue.
- Real deployments run at **trillions of messages/day** (LinkedIn, Uber, Netflix, Pinterest); banks use it for payments/fraud with strong durability; NYT stores all content as a Kafka log.
- The unifying idea: **one durable, replayable event log** feeding many independent consumers — decoupling producers from an ever-growing set of consumers.
- Know the **anti-patterns**: RPC, priority/delay queues, huge blobs, tiny apps, and strict global ordering are poor fits.

---

## 8) Quick glossary

- **Pub-sub:** publish/subscribe decoupling of producers and consumers.
- **Activity tracking:** streaming user events (LinkedIn's origin use case).
- **Stream processing:** transforming streams in flight (Streams/Flink/ksqlDB).
- **Event sourcing:** state as an immutable ordered event log; rebuild by replay.
- **CDC:** change data capture — stream a DB's changes (Debezium).
- **Outbox pattern:** atomic DB write + event publish via an outbox table + CDC.
- **Saga:** event-driven distributed transaction with compensations.
- **Feature store / pipeline:** real-time ML features from streams.
- **Kappa architecture:** single streaming path replacing batch + speed layers.
- **MirrorMaker 2 / cluster linking:** cross-cluster/region replication.
- **Keystone / Gairos / Samza:** Netflix / Uber / LinkedIn stream platforms.

---

## 9) Sources & further reading

- Apache Kafka — *Use cases*: <https://kafka.apache.org/uses>
- Apache Kafka — *Powered By* (adopters): <https://kafka.apache.org/powered-by>
- LinkedIn Engineering — *Kafka origin & the log abstraction* (Jay Kreps): <https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying>
- Netflix Tech Blog — *Keystone real-time stream processing platform*: <https://netflixtechblog.com/keystone-real-time-stream-processing-platform-a3ee651812a>
- Uber Engineering — *Gairos / real-time data platform on Kafka*: <https://www.uber.com/en-US/blog/gairos-scalability/>
- Uber Engineering — *uReplicator: cross-DC Kafka replication*: <https://www.uber.com/en-US/blog/ureplicator-apache-kafka-replicator/>
- Confluent — *Change Data Capture with Debezium & Kafka Connect*: <https://developer.confluent.io/courses/kafka-connect/change-data-capture/>
- Confluent — *Event sourcing & the New York Times case study*: <https://www.confluent.io/blog/publishing-apache-kafka-new-york-times/>
- Debezium — *CDC documentation*: <https://debezium.io/documentation/>
