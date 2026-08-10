# Kafka Ecosystem: Streams, Connect, Schema Registry & More — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-ecosystem-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Know the components that turn raw Kafka into a full **event-streaming platform**: **Kafka Connect** (integration), **Kafka Streams / ksqlDB / Flink** (processing), **Schema Registry** (data contracts), plus **tiered storage**, **KRaft**, and **cross-cluster replication**.

Cross-links: core log/partitions → note 01; the use cases these enable → note 03; delivery guarantees inside Streams → note 04.

---

## 1) The platform, layer by layer

```
        producers/apps        Kafka Connect (sources)     CDC (Debezium)
              \                     |                        /
               \                    v                       /
                =====================  KAFKA (brokers)  =====================
               /            (topics, partitions, replication, KRaft)         \
              /                     |                        \                 \
     Kafka Streams / ksqlDB     Schema Registry        Kafka Connect (sinks)   Flink/Spark
     (stream processing)        (data contracts)       (S3, Elastic, JDBC...)  (processing)
```

Kafka core = the log. The ecosystem adds **get data in/out** (Connect), **process it** (Streams/ksqlDB/Flink), and **govern it** (Schema Registry).

---

## 2) Kafka Connect — integration without code

- A framework to stream data **between Kafka and external systems** using reusable, config-driven **connectors** (no bespoke producer/consumer code).
- **Source connectors** pull *into* Kafka (JDBC, Debezium CDC, MQTT, S3, files); **sink connectors** push *out of* Kafka (S3, Elasticsearch, JDBC, Snowflake, BigQuery, HDFS).
- Runs as a **distributed cluster of workers**; scales via **tasks**; handles **offset tracking, retries, restarts, and DLQ** for you.
- **Single Message Transforms (SMTs):** lightweight per-record tweaks (mask a field, route by content, rename) inline in the pipeline.
- **Why it matters:** most "Kafka projects" are 80% moving data between systems — Connect makes that declarative and operable. CDC via Debezium (a source connector) is the flagship use (note 03).

---

## 3) Stream processing options

### Kafka Streams (a library, not a cluster)
- A **Java/Scala library** you embed in your app — no separate processing cluster. Scales by running more instances (they share partitions like a consumer group).
- **Stateless ops** (`map`, `filter`, `flatMap`) and **stateful ops** (`aggregate`, `count`, `join`, **windowing**).
- **State stores** (RocksDB) are backed by **compacted changelog topics** → fault-tolerant local state that rebuilds on restart.
- **KStream vs KTable:** a **KStream** is an event stream (append), a **KTable** is a changelog/materialized view (latest value per key). **Stream-table duality** lets you join events against current state.
- **Exactly-once** via `processing.guarantee=exactly_once_v2` (note 04).

### ksqlDB
- **SQL over streams.** `CREATE STREAM`, `CREATE TABLE`, `SELECT ... EMIT CHANGES`. Compiles to Kafka Streams under the hood. Great for filtering, joins, aggregations without writing Java.

### Apache Flink / Spark Structured Streaming
- External processing engines for heavier/lower-latency stateful workloads, complex event processing, and unified batch+stream. Flink is increasingly the default for large-scale streaming (Uber, Netflix, Pinterest). Choose Streams for "just a library inside my service", Flink for a managed processing platform.

---

## 4) Schema Registry — data contracts

- A service storing **versioned schemas** (**Avro**, **Protobuf**, **JSON Schema**) keyed by subject; producers/consumers register and fetch schemas by ID.
- Messages carry a small **schema ID**, not the whole schema → compact payloads + guaranteed decodability.
- **Compatibility rules** (BACKWARD/FORWARD/FULL) are enforced at registration so a producer can't ship a breaking change that would crash consumers.
- **Why it matters:** in a big org, topics are shared contracts between teams. The registry prevents "someone changed the event shape and broke five downstream services" — essential governance for the data backbone.

---

## 5) Storage, metadata & replication

### Tiered storage (KIP-405)
- Offload old log segments from broker disk to **object storage (S3/GCS)** while keeping recent data local.
- Decouples **storage from compute**: brokers stay small/fast, retention becomes effectively **unlimited/cheap**, and rebalancing is faster (less local data to move). Enables Kafka as long-term event store.

### KRaft (KIP-500)
- Kafka's built-in **Raft metadata quorum** replaces ZooKeeper (note 01). Simpler ops (one system), faster failover, supports **millions of partitions**. ZooKeeper mode removed in Kafka 4.0.

### Cross-cluster replication
- **MirrorMaker 2** (built on Connect) and **Cluster Linking** (Confluent) replicate topics across clusters/regions for **DR, migration, geo-locality, aggregation**. Uber's **uReplicator** is a hardened variant for cross-DC.

---

## 6) End-to-end: a governed streaming pipeline

```
MySQL --Debezium source connector--> [ db.orders ]  (Avro, schema in registry)
                                          │
                                 ksqlDB / Kafka Streams
                                 - join orders x customers (KTable)
                                 - windowed revenue per 1-min
                                          │
                                          ▼
                                 [ orders.enriched ]  (schema-checked)
                             ┌────────────┴─────────────┐
                             ▼                           ▼
            S3 sink connector (data lake)      Elasticsearch sink (search)
                             │
                    tiered storage keeps db.orders queryable for months
```

Connect gets data in/out, Streams/ksqlDB processes it, Schema Registry guarantees every stage agrees on shape, tiered storage keeps history cheap.

---

## 7) Reliability / security / ops lens

- **Reliability:** Connect handles retries/offsets/DLQ; Streams state is fault-tolerant via changelog topics; use EOS where dupes are unacceptable. Test connector restart & schema-evolution paths.
- **Security:** secure Connect worker configs/secrets (externalize credentials), lock down the Schema Registry (only owners register/evolve subjects), TLS/SASL/ACLs everywhere; be careful CDC topics carry PII.
- **Cost/scale:** tiered storage to cut broker disk cost; size Connect tasks and Streams instances to partition counts; watch changelog/compaction topic growth.
- **Observability:** connector task status (running/failed), SMT errors, DLQ rate, Streams state-store restore time & rebalance, schema compatibility rejections, MirrorMaker replication lag.

---

## 8) Key takeaways

- Kafka is a **platform**: **Connect** (config-driven in/out + CDC), **Streams/ksqlDB/Flink** (processing), **Schema Registry** (contracts), plus **tiered storage**, **KRaft**, and **replication**.
- **Kafka Streams is a library** (embed in your app) with fault-tolerant **RocksDB state** backed by **changelog topics**; **ksqlDB** is SQL on top; **Flink** for heavy managed streaming.
- **KStream (events) vs KTable (materialized latest-value)** and their duality power joins/aggregations.
- **Schema Registry** enforces compatibility so shared topics don't break downstream consumers.
- **Tiered storage** decouples storage from brokers (cheap, near-infinite retention); **KRaft** removes ZooKeeper; **MirrorMaker 2 / Cluster Linking** replicate across regions.

---

## 9) Quick glossary

- **Kafka Connect:** framework for source/sink connectors (no-code integration).
- **Connector / task / SMT:** integration unit / parallel worker / per-record transform.
- **Debezium:** CDC source connectors for databases.
- **Kafka Streams:** embeddable stream-processing library.
- **ksqlDB:** SQL interface over Kafka Streams.
- **KStream / KTable:** event stream / materialized changelog table.
- **State store / changelog topic:** local (RocksDB) state + its backing compacted topic.
- **Schema Registry:** versioned schema store with compatibility rules.
- **Avro / Protobuf / JSON Schema:** serialization formats with schemas.
- **Tiered storage (KIP-405):** offload old segments to object storage.
- **MirrorMaker 2 / Cluster Linking:** cross-cluster replication.

---

## 10) Sources & further reading

- Apache Kafka — *Kafka Connect*: <https://kafka.apache.org/documentation/#connect>
- Apache Kafka — *Kafka Streams documentation*: <https://kafka.apache.org/documentation/streams/>
- Confluent — *Schema Registry & data contracts*: <https://docs.confluent.io/platform/current/schema-registry/index.html>
- Confluent Developer — *ksqlDB course*: <https://developer.confluent.io/courses/ksqldb/intro/>
- KIP-405 — *Tiered storage*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-405%3A+Kafka+Tiered+Storage>
- Apache Kafka — *MirrorMaker 2 (KIP-382)*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-382%3A+MirrorMaker+2.0>
- Debezium — *Documentation*: <https://debezium.io/documentation/>
- Apache Flink — *What is Flink*: <https://flink.apache.org/what-is-flink/flink-architecture/>
