# Observability & Geospatial Analytics — Detailed Notes

> Companion deep-dive for the summary diagram: `maps-observability-analytics-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *how observability is added* to a location platform (the metrics/logs/traces + geospatial SLOs that keep dispatch healthy) and *how companies build analytics around the data* — the real-time OLAP + batch stack (Kafka → Flink/Spark → **Apache Pinot** with **H3 indexing** → dashboards, surge, forecasting, ML).

---

## 1) Two different questions this note answers

- **Observability** = *"Is the system healthy right now, and why did it break?"* → operational metrics, logs, traces, SLOs, alerts.
- **Analytics** = *"What is happening in the marketplace, and what should we do?"* → aggregations, dashboards, surge, demand forecasting, ML features, user-facing insights ("Orders near you").

Both are fed by the **same event stream** (the Kafka firehose from note 03) but land in different stores tuned for different queries.

---

## 2) Observability — the three pillars, plus a geospatial one

### Metrics (the golden signals for dispatch)
Track per-service **and per-geography (per H3/S2 cell, per city)**, because "healthy globally" can hide a broken downtown:

| Signal | Examples |
| --- | --- |
| **Marketplace health** | request rate, match rate, unfulfilled-request rate, time-to-match, surge multiplier distribution, supply/demand ratio per hexagon |
| **Location pipeline** | ping ingest rate, Kafka consumer lag, Redis memory/eviction, hot-shard skew, stale-driver ratio |
| **Dispatch quality** | offer accept rate, ETA error (predicted − actual), cancellation rate, driver idle time |
| **Live push (RAMEN)** | concurrent connections, push success %, push latency p95, reconnect rate |
| **Routing / map** | route-compute latency, map-match success rate, stale-speed coverage |

### Logs
Structured, sampled event logs (a full 2M/s ping log is unaffordable raw — sample + aggregate). Route to a searchable store (e.g. Elasticsearch/OpenSearch, or Pinot for high-QPS log analytics).

### Traces
Distributed tracing across the request path (gateway → location → matching → routing → push) to find *where* a slow match spent its time. Correlate a trace id across services.

### The geospatial pillar (specific to maps systems)
- **Cell-level heatmaps:** aggregate metrics by **H3 hexagon** so ops can *see* a stuck city block, a surge hotspot, or a dead GPS zone.
- **Geospatial SLOs:** e.g. "p95 time-to-match < X in cell Y," "ETA error < N% per segment."
- **Anomaly detection per cell:** a sudden supply collapse or demand spike in one hexagon should alert before it hurts users.

### SLOs, alerts, runbooks
Define SLOs (match rate, ETA accuracy, push success), alert on burn rate, and keep runbooks for the common failures (hot shard, Kafka lag, routing-weight staleness).

---

## 3) Analytics — the lambda-ish stack (real-time + batch)

The whole point: **decouple analytical queries from the OLTP path** so heavy aggregation never slows dispatch. The pattern (Uber's stack):

```
OLTP stores (MySQL, Cassandra)  --change logs-->  Kafka
                                                   │
                     ┌─────────────────────────────┼───────────────────────────┐
                     v (real-time)                                              v (batch)
                Apache Flink  (AthenaX = SQL on Flink)                      Apache Spark
                     │  transform / window / upsert                              │
                     v                                                           v
              Apache Pinot  (real-time OLAP, H3-indexed) <---- deep storage ---- HDFS / S3 lake
                     │                                                           │
       user-facing analytics, dashboards, surge inputs           ML training (Michelangelo),
       ("Orders near you"), high-QPS queries                     reports, warehouses (Presto)
```

### Apache Pinot — the real-time OLAP engine
- Distributed OLAP store for **low-latency, high-QPS, user-facing** analytics on TB–PB data; ingests from **Kafka (near real-time)** *and* **Hadoop/HDFS (batch)**.
- **Data freshness within seconds** of an event being produced — new orders/positions are queryable almost immediately.
- **Geospatial indexing built on H3:** Uber contributed H3-based geo-indexing to Pinot so `ST_Distance`/radius queries don't scan every row globally — they use the hexagon + neighbor-ring approximation to prune. This is what powers **"Orders near you"** at high QPS.
- **Upsert on ingestion:** correct/replace records in place (e.g. a ride fare corrected, an UberEats order's delivery status updated) so real-time results stay accurate.

### Flink / Spark / AthenaX
- **Flink** = stateful **stream** processing (windowed supply/demand → surge; exactly-once for financial/ads events).
- **AthenaX** = SQL-on-Flink so analysts declare streaming jobs in SQL.
- **Spark** = heavy **batch** (daily/weekly aggregates, ML feature backfills, map pipeline).
- **HDFS/S3** = cheap deep storage / data lake; **Presto/Neutrino** for ad-hoc SQL on Pinot/lake.

### Gairos — the real-time data intelligence platform
Uber's **Gairos** ingests Kafka topics into **Elasticsearch** clusters and serves real-time queries for **surge pricing, max-dispatch-ETA, and demand/supply forecasting** — surge reads demand & supply **per hexagon** to compute the multiplier for a location and time.

---

## 4) What the analytics actually produce

- **Surge / dynamic pricing:** per-H3-cell supply vs. demand → multiplier (note 02). A closed real-time loop off the same stream.
- **Demand & supply forecasting:** predict where rides/orders will spike (events, weather, rush hour) to pre-position drivers ("driver surge" nudges, carbon suggestions).
- **ETA & route ML:** DeepETA and prep-time/travel-time models (note 02) are trained on historical trips in the lake and served via **Michelangelo**.
- **User-facing analytics:** "Orders near you," ETA bands, heatmaps, driver earnings dashboards.
- **Ops & business intelligence:** city dashboards, funnel analysis, experiment (switchback) readouts for dispatch algorithm changes.
- **Fraud & safety:** GPS-spoofing detection, impossible-travel checks, anomaly flags from location patterns.

---

## 5) End-to-end: one event, both worlds

```
driver ping / order event
   -> Kafka
      ├── (observability) metrics agg per H3 cell -> dashboards + alerts (SLO burn)
      ├── (real-time analytics) Flink window -> Pinot (H3-indexed) -> "Orders near you", surge
      └── (batch) Spark -> HDFS/S3 lake -> ML training (Michelangelo) + warehouse reports
```

The same firehose simultaneously answers "is dispatch healthy?" and "what should the price/forecast/model be?" — never by querying the live serving stores.

---

## 6) Reliability / security / ops lens

- **Reliability:** analytics is downstream of Kafka, so it can lag or be replayed without affecting dispatch; Pinot runs active-active across regions with upsert for correctness. Never let a dashboard query hit the hot geo store.
- **Cost:** sample logs, roll up to coarse H3 for long-term retention, tier hot (Pinot/ES) vs. cold (lake).
- **Security/privacy:** aggregate/anonymize before analytics; coarsen resolution for user-facing and exported data; restrict raw-trace access; enforce retention.
- **Ops:** the analytics platform itself needs observability (Kafka lag, Pinot ingestion lag, segment health, query p99).

---

## 7) Key takeaways

- **Observability** = metrics + logs + traces **plus a geospatial pillar**: aggregate everything **per H3 cell** and set **geospatial SLOs** so a broken city block is visible.
- Watch the dispatch golden signals: **match rate, time-to-match, ETA error, offer accept rate, push success, Kafka lag, hot-shard skew, stale-driver ratio.**
- **Analytics is decoupled from OLTP** via the **Kafka firehose → Flink/Spark → Apache Pinot / lake** pattern, keeping heavy queries off the serving path.
- **Apache Pinot with H3 geo-indexing** gives **seconds-fresh, high-QPS, user-facing** geospatial analytics ("Orders near you") and supports **upsert** for correctness.
- Analytics powers **surge, forecasting, ETA/prep ML (Michelangelo), fraud detection, and dashboards** — a closed loop feeding back into dispatch (note 02).
- **Gairos** (Kafka → Elasticsearch) is Uber's real-time platform for surge, max-dispatch-ETA, and forecasting, all per hexagon.

---

## 8) Quick glossary

- **Observability:** metrics + logs + traces to know system health and diagnose failures.
- **Golden signals:** the few metrics that best reflect service health.
- **Geospatial SLO:** a reliability target scoped to a cell/region (e.g. p95 time-to-match).
- **OLAP:** analytical query engine (aggregations) vs. OLTP (transactions).
- **Apache Pinot:** real-time OLAP store; H3-indexed geo queries; seconds-fresh; upsert.
- **Apache Flink / AthenaX:** stream processing / SQL-on-Flink.
- **Apache Spark:** large-scale batch processing.
- **Data lake (HDFS/S3):** cheap durable storage for history & ML.
- **Gairos:** Uber's real-time data intelligence platform (surge, ETA, forecasting).
- **Michelangelo:** Uber's ML platform for training/serving models (e.g. DeepETA).
- **Upsert:** insert-or-update on ingestion to keep real-time results accurate.

---

## 9) Sources & further reading

**Real-time geospatial analytics**
- Uber Engineering — *'Orders Near You' and user-facing analytics on real-time geospatial data (Pinot + H3 geo-indexing)*: <https://www.uber.com/us/en/blog/orders-near-you/>
- Apache Pinot — *Geospatial support (H3 index, `ST_Distance`)*: <https://docs.pinot.apache.org/basics/indexing/geospatial-support>
- Uber Engineering — *Real-time exactly-once ad event processing with Flink, Kafka & Pinot (upsert)*: <https://www.uber.com/us/en/blog/real-time-exactly-once-ad-event-processing/>

**Real-time platform & surge**
- Uber Engineering — *Gairos: real-time data intelligence platform (surge, dispatch ETA, forecasting)*: <https://www.uber.com/us/en/blog/gairos-scalability/>
- Uber Engineering — *Michelangelo ML platform*: <https://www.uber.com/blog/michelangelo-machine-learning-platform/>

**Analytics stack**
- Apache Pinot documentation: <https://docs.pinot.apache.org/>
- Apache Flink documentation: <https://flink.apache.org/what-is-flink/flink-architecture/>
- Google SRE Book — *Monitoring distributed systems (golden signals, SLOs)*: <https://sre.google/sre-book/monitoring-distributed-systems/>
