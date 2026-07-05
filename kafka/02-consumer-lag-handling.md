# Kafka Consumer Lag — Detection, Effects & Handling — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-consumer-lag-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *what consumer lag is*, *how to measure it*, *what real-world damage it causes* (with concrete scenarios), and the full toolbox for *handling / preventing* it — from partition/consumer scaling to poll tuning, backpressure, and dead-letter queues.

Cross-links: fundamentals & offsets → note 01; ordering/EOS trade-offs → note 04; operational scaling → note 06.

---

## 1) What lag actually is

For a single partition:

```
lag = log-end-offset (LEO)  −  last committed offset
      "newest message"          "how far the consumer got"
```

- **Log-end offset (LEO):** offset of the next message the producer will write — i.e. the head of the partition.
- **Committed offset:** the last offset the consumer group acknowledged (in `__consumer_offsets`).
- **Group lag:** sum of per-partition lag across all partitions the group owns.

Lag is a **queue depth in messages**, not seconds. Two derived views matter more operationally:

- **Time lag (latency):** "how old is the record I'm about to process?" ≈ `now − timestamp(next record)`. This is what SLAs care about.
- **Lag trend (derivative):** is lag **flat, growing, or shrinking**? A steady lag of 5,000 is fine; a lag climbing 10k/min will page you.

> Golden rule: **produce rate > consume rate ⇒ lag grows unbounded.** Lag is the visible symptom of a consumer that can't keep up (or has stopped).

---

## 2) How to measure & detect lag

### CLI (quick check)
```bash
# Show CURRENT-OFFSET, LOG-END-OFFSET, and LAG per partition
kafka-consumer-groups.sh --bootstrap-server broker:9092 \
  --describe --group billing-service
```
Columns: `TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST`.

### Programmatic / metrics
- **Consumer JMX:** `records-lag-max` (per-consumer, but only reflects partitions it owns and only while polling).
- **Burrow** (LinkedIn): evaluates lag *status* (OK/WARN/ERR) using offset **trend**, not a fixed threshold — avoids false alarms on bursty traffic.
- **Kafka Lag Exporter / kafka-exporter → Prometheus + Grafana:** exports per-group, per-partition lag **and estimated time lag**; alert on trend.
- **Cloud/managed:** Confluent `consumer_lag`, MSK `MaxOffsetLag`/`SumOffsetLag` (CloudWatch).

### What to alert on (good practice)
- Alert on **sustained growth** or **time-lag > SLA** (e.g. "records older than 60s"), not on an absolute message count.
- Alert on **stalled/empty group** (a consumer that stopped committing → lag frozen then exploding).
- Watch **rebalance storms** (lag spikes every few minutes = flapping consumers).

---

## 3) Why lag happens (root causes)

| Category | Cause | Signature |
| --- | --- | --- |
| **Under-provisioned** | too few consumers/partitions for the load | lag grows with traffic, all consumers busy |
| **Slow processing** | heavy per-record work (DB call, external API, big computation) | high processing time, low throughput |
| **Downstream backpressure** | sink DB / API is slow or rate-limited | consumer blocked on writes |
| **Poison / stuck message** | one record repeatedly fails & retries, blocking the partition | lag stuck on one partition, error loop |
| **Skew / hot partition** | one key dominates (`hash(hotKey)`) | one partition's lag high, others fine |
| **Rebalance thrash** | `max.poll.interval.ms` exceeded → consumer kicked → rebalance → repeat | periodic lag saw-tooth |
| **Consumer down / crash-loop** | deploy bug, OOM, GC pause | lag climbs linearly, no commits |
| **Traffic spike** | flash sale, batch job, incident retries | sudden step-up in produce rate |

---

## 4) Real scenarios & the effect of lag

Lag is not abstract — it directly degrades product behavior. Concrete cases:

### A) Ride-hailing / food delivery — the map goes stale
The location pipeline (Uber/Swiggy-style, see [`../maps/03-location-ingestion-scale-and-live-updates.md`](../maps/03-location-ingestion-scale-and-live-updates.md)) streams GPS pings through Kafka. If the geo-consumer lags by 30s:
- **Effect:** the driver's blue dot on the rider's map is 30 seconds behind reality; dispatch matches on **stale supply**, ETAs are wrong, and "arriving now" fires when the driver is still 3 blocks away. Lag here is *literally* a stale map.

### B) Payments — delayed settlement & duplicate-risk windows
A `payments.captured` consumer feeding ledger/settlement lags during a sale spike:
- **Effect:** customer is charged but the order-confirmation/ledger event is delayed → "did my payment go through?" support tickets, delayed merchant settlement, and a longer window where reconciliation/fraud checks run on old data. If someone "fixes" it by disabling commits, you risk **reprocessing = double side-effects**.

### C) Fraud / security detection — the alert arrives too late
A fraud model consumes a transaction stream. 10-minute lag means:
- **Effect:** fraudulent transactions are flagged *after* the money is gone. Detection latency = money lost. Here lag converts directly to fraud losses.

### D) Log/metrics analytics — dashboards lie
Observability pipelines push logs/metrics through Kafka to Elasticsearch/Pinot. Consumer lag →
- **Effect:** during the exact incident you're debugging, your dashboards are minutes stale, so on-call makes decisions on old data. Lag is most dangerous precisely when traffic (and lag) is highest.

### E) CDC / cache invalidation — you serve stale reads
Debezium CDC → Kafka → cache-invalidation consumer. Lag →
- **Effect:** the DB changed but the cache-buster event hasn't been consumed → users see stale prices/inventory. Oversells during flash sales trace back to invalidation lag.

**The through-line:** lag turns a "real-time" system into a "several-minutes-ago" system, silently, and worst at peak load. And retention makes it dangerous: if lag time **exceeds `retention.ms`**, unconsumed records are **deleted before being read → permanent data loss**.

---

## 5) How to handle lag (the toolbox)

Ordered from "reduce work per message" to "add capacity" to "shed load".

### Speed up the consumer
1. **Increase parallelism = add consumers up to partition count.** The single biggest lever. Remember: **max useful consumers in a group = number of partitions**. If you're already at the cap, you must **repartition** (add partitions — note the ordering caveat below).
2. **Batch processing & batched I/O.** Process the whole `poll()` batch and do **one bulk DB write / one bulk API call** instead of per-record round-trips. Tune `max.poll.records`, `fetch.min.bytes`, `fetch.max.wait.ms`.
3. **Async / pipelined processing** with bounded in-flight work; commit offsets only after successful processing (keep at-least-once safety).
4. **Move slow work off the hot path.** Don't do synchronous 300 ms API calls inline — enrich via a cache, or hand off to a second topic/worker pool.
5. **Right-size polling to avoid rebalances.** If processing a batch can exceed `max.poll.interval.ms`, either lower `max.poll.records` or raise the interval — otherwise the broker thinks the consumer died, triggering a rebalance that *makes lag worse*.

### Add / rebalance capacity
6. **Add partitions** to raise the parallelism ceiling. Caveat: increasing partitions **changes key→partition mapping** for new data and can break per-key ordering; plan it (over-provision partitions up front instead).
7. **Autoscale consumers** on the lag metric itself (e.g. **KEDA** Kafka scaler / HPA on `consumer_lag`) so capacity tracks the backlog automatically.
8. **Fix skew.** Re-key or add a salt to spread a hot key across partitions; or route the hot key to a dedicated partition/consumer.

### Protect the pipeline (don't let one bad message wreck you)
9. **Dead-letter topic (DLT/DLQ).** After N retries, send the poison message to `orders.DLT` and **move on** so it doesn't block the partition. Investigate the DLT separately.
10. **Retry topics with backoff** (Spring Kafka `@RetryableTopic`, or tiered retry topics `retry-5s`, `retry-1m`) so transient failures don't spin-block the main topic.
11. **Backpressure / circuit-break** to the downstream sink (pause the consumer with `pause()/resume()` when the sink is unhealthy) instead of hammering it.

### Recover from a huge backlog
12. **Temporarily scale out + widen batches**, then scale back once caught up.
13. **Offset reset as a deliberate choice:** if the backlog is worthless (e.g. stale telemetry) and *reprocessing is acceptable to skip*, `--reset-offsets --to-latest` to "skip to now". **Only for droppable data** — you're discarding messages.
14. **Prevent retention-driven loss:** if lag time is approaching `retention.ms`, **increase retention** (or tiered storage) *first* so you don't lose data while catching up.

---

## 6) End-to-end: detect → diagnose → remediate

```
① DETECT   Grafana alert: billing-service time-lag > 60s and rising
② TRIAGE   kafka-consumer-groups --describe
           -> lag concentrated on orders-3 (hot partition) + all consumers 100% CPU
③ DIAGNOSE per-record it does a synchronous inventory API call (250ms)
④ FIX (now)   scale consumers 4 -> 6 (partitions=6), enable batched API calls
   FIX (poison) one SKU errors every time -> route to orders.DLT after 3 retries
   FIX (skew)    re-key hot SKU with salt so it spreads across partitions
⑤ GUARDRAIL  KEDA autoscale on consumer_lag; alert on trend not absolute
⑥ VERIFY   lag drains to ~0, time-lag < 5s, no rebalance storms
```

---

## 7) Reliability / security / ops lens

- **Reliability:** never let lag time exceed `retention.ms` (silent data loss). Keep consumers **idempotent** so at-least-once reprocessing after a lag recovery is safe (note 04). Use DLTs so one poison record can't stall a partition indefinitely.
- **Capacity:** provision partitions for *peak* parallelism, not average — you can add consumers instantly but adding partitions is disruptive.
- **Security:** DLTs may contain sensitive payloads — apply the same ACL/encryption as the source topic; don't dump raw PII into a widely-readable debug topic.
- **Observability:** dashboard **time-lag per group**, **lag trend**, **rebalance rate**, **max.poll interval breaches**, **DLT rate**. Page on trend + SLA breach, not raw count.

---

## 8) Key takeaways

- **Lag = newest offset − committed offset**; track **time-lag** and **trend**, not just message count.
- Lag grows whenever **produce rate > consume rate**; it's the symptom of an under-scaled, slow, stuck, or crashed consumer.
- **Effects are product-visible:** stale maps, delayed settlements, late fraud alerts, lying dashboards, stale caches — and worst at peak.
- **Data loss risk:** if lag time > `retention.ms`, unread messages are deleted forever.
- **Handle it by:** adding consumers (up to partition count), batching/async processing, avoiding rebalance-triggering long polls, fixing skew, and isolating poison messages with **DLT + retry topics**.
- **Autoscale on the lag metric** (KEDA) and alert on **trend/time**, not absolute numbers.

---

## 9) Quick glossary

- **Lag:** unread backlog = LEO − committed offset.
- **LEO (log-end offset):** offset of the next message to be produced.
- **Time lag:** age of the next record to process (SLA metric).
- **Burrow:** LinkedIn tool that evaluates lag by trend/status.
- **Kafka Lag Exporter:** exports lag + time-lag to Prometheus.
- **`max.poll.interval.ms`:** max gap between polls before the broker evicts the consumer (triggers rebalance).
- **`max.poll.records`:** batch size returned per `poll()`.
- **DLT / DLQ:** dead-letter topic for messages that fail after retries.
- **Retry topic:** staging topic for delayed re-attempts (backoff).
- **KEDA:** Kubernetes event-driven autoscaler (scales on lag).
- **Skew / hot partition:** uneven load from a dominant key.
- **Offset reset:** deliberately move committed offset (e.g. to-latest) — drops or replays data.

---

## 10) Sources & further reading

- Apache Kafka — *Consumer configs & offset management*: <https://kafka.apache.org/documentation/#consumerconfigs>
- LinkedIn Engineering — *Burrow: Kafka consumer lag checking*: <https://github.com/linkedin/Burrow>
- Confluent — *Monitoring consumer lag*: <https://developer.confluent.io/courses/kafka-monitoring/consumer-lag/>
- Confluent — *Error handling & dead letter queues (Kafka Connect / Streams)*: <https://www.confluent.io/blog/error-handling-patterns-in-kafka/>
- Spring for Apache Kafka — *Non-blocking retries & `@RetryableTopic` / DLT*: <https://docs.spring.io/spring-kafka/reference/kafka/annotation-error-handling.html#retry-topic>
- KEDA — *Apache Kafka scaler (autoscale on consumer lag)*: <https://keda.sh/docs/latest/scalers/apache-kafka/>
- Seznam / Lightbend — *Kafka Lag Exporter*: <https://github.com/seglo/kafka-lag-exporter>
