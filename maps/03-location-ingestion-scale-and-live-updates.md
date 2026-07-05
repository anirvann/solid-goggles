# Location Ingestion at Scale & Live Updates — Detailed Notes

> Companion deep-dive for the summary diagram: `maps-location-ingestion-live-updates-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *the transaction rate* of location data (how many GPS pings/sec), *how to manage that high volume* (batching, streaming backbone, in-memory + TTL, hot/cold tiering), and *how live updates are relayed* to phones (the "moving car on the map") via persistent push (Uber **RAMEN**: SSE → gRPC).

---

## 1) The firehose: how much data, how fast?

This is the "what is the transaction rate?" question, answered concretely.

- Each active driver/courier app emits a GPS ping every **~2–5 seconds**.
- At ~**10M** active drivers that is roughly **~1.25–2 million location writes per second** globally (Uber has publicly cited **~1.25M GPS updates/sec**).
- The **read** side ("find nearby drivers", live-tracking refreshes) is on the order of **1M+ requests/sec**.
- Push side: Uber's real-time push platform holds **~1.5M concurrent connections** and delivers on the order of **250K–1.5M messages/sec**.

So you're designing for a sustained, spiky, write-dominated firehose — not request/response CRUD.

### Why you can't just write each ping to a normal database
- A plain OLTP row-write per ping means 1–2M writes/sec of tiny payloads → most SQL/NoSQL clusters either fall over or must be scaled absurdly.
- Worked example: **2M writes/s × ~100 bytes to DynamoDB on-demand ≈ >$200,000/day.** Direct-to-durable-DB is economically and operationally wrong for live pings.

The write path must be **cheap, in-memory, expiring, and streamed** — never a synchronous durable write.

---

## 2) Managing high volume — five levers

1. **Batch / aggregate on the client & edge.** Buffer a few points on the phone (e.g. 3 points, smoothed with a Kalman filter) and send one message, cutting request count. Aggregate again server-side over a short interval before any persistence.
2. **In-memory hot store with TTL.** Write current position to **Redis GEO / Redis Cluster / Tile38** — overwrite memory instead of reallocating, and **auto-expire** silent drivers (`ZREMRANGEBYSCORE` / TTL to drop anyone quiet >3–5 s). The hot store is a **cache**, not the source of truth.
3. **Shard by spatial cell, not by city.** Partition Redis by **S2 level-5 (~1 km²)** or **H3** cell so no single downtown shard becomes a hotspot; this removes global write-lock contention (Lyft's approach). The classic mechanism is **application-layer sharding** — Uber's **Ringpop** holds a **consistent hash ring** over stateful in-memory workers, keyed by the driver's **S2 cell**, with **SWIM gossip** membership and **TChannel** handle-or-forward routing, so a worker owns a *geographic area* and clients need no knowledge of the partitioning (see note 01).
4. **Stream everything through a log.** Publish every ping to **Apache Kafka** (Uber uses Kafka + uReplicator for cross-DC fan-out). One durable, replayable log fans out to *many* consumers (geo store, surge, ETA, analytics, ML) — decoupling producers from consumers.
5. **Tier hot vs. cold.** Live position → memory (seconds of retention). History → **data lake (HDFS/S3)** and **OLAP (Pinot)** for analytics (note 05). Trip records → durable OLTP (Cassandra/DynamoDB/MySQL).

---

## 3) The streaming backbone (event-driven, not polling)

```
 driver app --GPS batch--> gateway --> Location Service
        |                                   |
        |                        latLngToCell (H3, µs)
        v                                   v
   [ Kafka: driver.location.updates ]  <----+
        |            |             |
        v            v             v
   Redis GEO     Flink          Data Lake
  (nearby        (supply/demand  (HDFS/S3 -> Pinot,
   lookups)       -> surge)       history, ML)
```

- **Kafka** = the shock absorber and single fan-out point; consumers scale independently and can **replay** to rebuild state.
- **Apache Flink** does stateful stream processing (windowed supply/demand per hexagon → surge; ETA aggregates).
- **Redis GEO / Tile38** serves the low-latency "nearby" reads for dispatch (note 02).
- The lake + **Apache Pinot** serve analytics and ML training (note 05).

This is why the platform can absorb 1M+/s: it "avoids expensive geospatial computation entirely" on the write path — cheap H3 mapping + append to a log + overwrite in memory.

---

## 4) Relaying live updates to phones — the "living map"

The blue car gliding on your screen is **not polling**. Polling at this scale (millions of apps every second) would melt the backend and drain batteries. Instead platforms hold a **persistent connection per app** and **push**.

### Uber RAMEN (Real-time Asynchronous MEssaging Network)
The canonical, publicly documented design.

**Evolution of the transport protocol:**
- **2015 — SSE over HTTP/1.1.** Server-Sent Events: server→client only (unidirectional). Acks/retries had to be bolted on for at-least-once. Client reconnects with `/ramen/receive?seq=N` carrying the last sequence number.
- **2019+ — gRPC bidirectional streaming over QUIC/HTTP3.** Full-duplex: the client can **ACK on the same stream instantly** (no extra round-trip), Protobuf shrinks payloads/CPU, and QUIC removes head-of-line blocking → ~**45% better p95** connection latency and higher push success.

**Server-side components:**
- **Streamgate** — Netty-based service that **holds the millions of persistent connections** (stateful: a given user's socket lives on a specific server).
- **StreamgateFE** — front-end proxy that **routes by userID** to the correct Streamgate shard; sharding/rebalancing managed by **Apache Helix + ZooKeeper** (so a server failure reshuffles connections without a single point of failure).
- **Fireball** — the **decision engine**: subscribes to the event bus (driver accepted, timer expired, driver moved) and decides *when/what* to push (priority, TTL, dedup). "Driver 5 miles away moving? not urgent. Driver turning your corner? push now."
- **Persistence** — **Redis** (fast message cache) + **Cassandra** (durable) to back **at-least-once** delivery.

### Delivery guarantees & resilience
- **At-least-once + sequence numbers:** every message carries a seq; a client that drops (tunnel, lift) reconnects and resumes exactly where it left off — no dupes, no gaps.
- **Heartbeats + exponential backoff** reconnection keep the stream healthy.
- **Fallback to APNs/FCM** push notifications to wake a backgrounded/killed app.

### WebSockets — the simpler cousin
Not everyone builds RAMEN. Many food-delivery customer-tracking screens use plain **WebSockets** (full-duplex over one TCP connection): the app opens a connection, **subscribes to an order-specific channel**, and the server publishes each new courier position to that channel (often fanned out via Redis pub/sub), with the frontend animating the marker. One connection carries hundreds of updates at sub-100 ms latency — the same "push, don't poll" principle as RAMEN, with less bespoke infrastructure.

### A concrete open-source example: Namma Yatri
India's **Namma Yatri** (a Juspay spin-off, built on **ONDC + the Beckn protocol** — an open network, "UPI for mobility") ships its stack in the open, and it mirrors this note almost exactly: a dedicated **`location-tracking-service` (Rust)** for ingesting/serving driver positions, and a **`notification-service` (Rust)** implementing **gRPC bidirectional streaming** with **Redis Streams as the message broker** — a readable, real implementation of the persistent-push pattern described above.

### Client-side smoothing
- Raw pings arrive every few seconds and are noisy. The app **interpolates/animates** between points (and can use client-side map data + map-matching, note 04) so the marker glides smoothly along the road instead of teleporting.

---

## 5) End-to-end: one location update, two destinations

```
① Driver moves
   -> phone: GPS -> Kalman filter -> batch 3 points
   -> gRPC stream -> LB -> Location Service

② Location Service
   -> GPS -> H3 index
   -> write Redis GEO (overwrite + TTL)   [serves dispatch reads]
   -> produce to Kafka "driver.location.updates"

③ Kafka consumers
   ├── Flink   -> supply/demand per hexagon -> surge
   └── Lake    -> history / ML / dashboards (note 05)

④ Rider is tracking this driver
   -> Fireball decides "push position update"
   -> RAMEN (Streamgate) -> gRPC stream -> rider phone
   -> app interpolates -> car glides on the map

Match offer -> accept -> live tracking, total elapsed < ~2s
```

---

## 6) Reliability / security / ops lens

- **Reliability:** treat the hot geo store as **rebuildable** from Kafka; make push **at-least-once** with seq-number dedup so a dropped connection never loses a ride offer. Design for reconnect storms (backoff, jitter).
- **Overload protection (Grab Spampede):** during demand spikes, count unallocated bookings per **(service, geohash-int cell, time bucket)** with a Redis `INCR`, and **circuit-break** new bookings for that cell/time once a threshold is crossed — a location-aware load shedder that protects the whole pipeline.
- **Scale/cost:** batch on the client, shard by cell, keep pings out of expensive per-write OLTP. The single biggest cost mistake is durable-writing every ping.
- **Security/privacy:** encrypt the stream (TLS/QUIC); precise trails are sensitive PII — restrict access, retain minimally, and coarsen resolution for anything exported.
- **Observability:** ingest rate, Kafka lag, Redis memory/eviction & hot-shard skew, stale-driver ratio, connection count, push success rate, push latency p95, reconnect rate (note 05).

---

## 7) Key takeaways

- **Transaction rate is the whole story:** ~2–5 s pings × millions of drivers ≈ **~1–2M writes/sec**, with **1M+ reads/sec** and **~1.5M live connections**.
- Never durable-write each ping (a naive DynamoDB path is **>$200k/day**): **batch → in-memory + TTL → Kafka stream → fan-out**.
- **Shard the hot store by spatial cell** (S2/H3), not by city, to kill hot-shard contention.
- Live updates are **pushed over persistent connections**, never polled — Uber **RAMEN**, which migrated **SSE → gRPC bidi over QUIC/HTTP3**.
- Push infra is **stateful and sharded** (Streamgate + StreamgateFE + Helix), with **Fireball** deciding what to send and **Redis+Cassandra** guaranteeing at-least-once via **sequence numbers**; falls back to **APNs/FCM**. Simpler apps use plain **WebSockets + per-order channels**; **Namma Yatri** open-sources the pattern (Rust location + gRPC-streaming notification over Redis Streams).
- Clients **interpolate** noisy pings so the marker glides.
- Add **location-aware overload protection** (Grab Spampede) to shed load per cell during spikes.

---

## 8) Quick glossary

- **Ping / location update:** a driver's periodic GPS report (every ~2–5 s).
- **Transaction rate:** sustained events/sec — here ~1–2M writes/sec.
- **Kafka:** distributed append-only log used as the streaming backbone / fan-out.
- **Flink:** stateful stream processor (windowed supply/demand → surge).
- **TTL / `ZREMRANGEBYSCORE`:** auto-expiry of stale drivers in the hot store.
- **RAMEN:** Uber's real-time push platform.
- **SSE:** Server-Sent Events (unidirectional server→client push).
- **gRPC bidi / QUIC / HTTP3:** full-duplex streaming transport (RAMEN v2).
- **Streamgate / StreamgateFE:** connection-holding service / userID-sharded proxy.
- **Fireball:** decides when/what to push (priority, TTL, dedup).
- **At-least-once + sequence number:** delivery guarantee + resume-after-drop mechanism.
- **WebSocket:** full-duplex TCP channel; common for per-order customer tracking.
- **Ringpop:** application-layer sharding of stateful location workers (consistent hash + SWIM + TChannel).
- **Spampede:** Grab's per-cell/time Redis circuit breaker for demand-spike overload.
- **APNs / FCM:** OS push services used as wake-up fallback.

---

## 9) Sources & further reading

**Scale & ingestion**
- Uber Engineering — *Uber's real-time data intelligence platform (Gairos): surge, dispatch ETA, forecasting on Kafka streams*: <https://www.uber.com/us/en/blog/gairos-scalability/>
- Hello Interview — *Design a ride-sharing service (write volume ~2M/s, DynamoDB cost, Redis geo + TTL)*: <https://www.hellointerview.com/learn/system-design/problem-breakdowns/uber>
- Lyft Engineering (via System Design newsletter) — *Redis cluster sharded by S2 cells, expiry of stale drivers*: <https://newsletter.systemdesign.one/p/lyft-engineering>

**Live updates / push**
- Uber Engineering — *Uber's Real-Time Push Platform (RAMEN, SSE design)*: <https://www.uber.com/en-US/blog/real-time-push-platform/>
- Uber Engineering — *Uber's Next-Gen Push Platform on gRPC (SSE → gRPC/QUIC, Streamgate/StreamgateFE, Helix)*: <https://www.uber.com/en-US/blog/ubers-next-gen-push-platform-on-grpc/>
- Uber Engineering — *Ringpop: application-layer sharding (Geospatial service)*: <https://www.uber.com/en-US/blog/ringpop-open-source-nodejs-library/>
- Grab Engineering — *Preventing app performance degradation from ride-demand spikes (Spampede)*: <https://engineering.grab.com/preventing-app-performance-degradation-due-to-sudden-ride-demand-spikes>
- Namma Yatri — open-source `location-tracking-service` (Rust) & `notification-service` (gRPC streaming + Redis Streams): <https://github.com/nammayatri>

**Streaming infra**
- Apache Kafka documentation: <https://kafka.apache.org/documentation/>
- Apache Flink — *Stateful stream processing*: <https://flink.apache.org/what-is-flink/flink-architecture/>
