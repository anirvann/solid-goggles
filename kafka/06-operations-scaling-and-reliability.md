# Kafka Operations, Scaling & Reliability — Detailed Notes

> Companion deep-dive for the summary diagram: `kafka-operations-scaling-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Run Kafka in production: **choose partition counts & replication**, **tune producers/consumers for durability vs throughput**, **manage rebalances**, **monitor the right vitals**, **secure the cluster**, and **plan capacity/DR**.

Cross-links: architecture/ISR → note 01; lag remediation → note 02; EOS durability → note 04; tiered storage/KRaft → note 05.

---

## 1) Partition strategy — the most consequential decision

Partition count drives **parallelism, ordering, and rebalance cost**.

- **More partitions →** more consumer parallelism + throughput, **but** more open files, more memory, longer leader-election/rebalance, more end-to-end latency.
- **Sizing heuristic:** `partitions ≈ max(target_throughput / per_partition_throughput, desired_consumer_parallelism)`. Measure per-partition throughput on your hardware (often tens of MB/s).
- **Over-provision (a bit):** you can add partitions later, but it **breaks key→partition mapping / per-key ordering** for new data (note 04). Pick a comfortable number up front.
- **Keying:** choose a key that spreads load evenly *and* groups what must stay ordered (e.g. `accountId`). Watch for **hot keys** (skew) → salt or dedicate a partition (note 02).
- **Rule of thumb ceiling:** keep partitions-per-broker in the low thousands (KRaft raises the cluster-wide ceiling into the millions, but per-broker limits still apply).

---

## 2) Replication & durability config

The canonical durable setup:

| Setting | Value | Why |
| --- | --- | --- |
| `replication.factor` | **3** | survive 1 broker loss (2 for DR headroom) |
| `min.insync.replicas` | **2** | with `acks=all`, tolerate 1 down and still accept writes |
| `acks` (producer) | **all** | leader + all ISR must persist before ack |
| `enable.idempotence` | **true** | no duplicate on retry (default) |
| `unclean.leader.election.enable` | **false** | never elect a stale replica → no silent data loss |
| `broker.rack` | set per AZ | spread replicas across racks/AZs |

The interplay: with `RF=3` + `min.insync.replicas=2` + `acks=all`, one broker can die with **zero data loss and continued writes**. If a *second* ISR drops so ISR < 2, producers get errors (fail-safe) rather than silently losing durability.

---

## 3) Throughput vs latency tuning

**Producer**
- Throughput: raise `batch.size`, `linger.ms` (e.g. 5–100 ms), enable `compression.type=lz4/zstd`.
- Latency: lower `linger.ms`; keep `acks=all` for safety unless the data is droppable.

**Consumer**
- Throughput: raise `fetch.min.bytes`, `fetch.max.wait.ms`, `max.poll.records`; do **bulk** downstream writes.
- Stability: set `max.poll.interval.ms` above your worst-case batch processing time to avoid eviction/rebalance (note 02).

**Broker/OS**
- Give RAM to the **page cache** (Kafka relies on it + zero-copy); fast sequential-write disks (NVMe/SSD); separate disks for data vs OS; tune file descriptors and network threads.

---

## 4) Rebalancing & consumer group health

Rebalances redistribute partitions when members join/leave — and they **pause consumption**, so minimize them.

- **Cooperative / incremental rebalancing** (`CooperativeStickyAssignor`) only moves the partitions that must move, instead of stop-the-world revoking everything.
- **Static membership** (`group.instance.id` + higher `session.timeout.ms`) avoids a rebalance when a consumer restarts quickly (e.g. rolling deploy / k8s pod restart).
- **Avoid triggers:** long GC pauses, exceeding `max.poll.interval.ms`, and flapping pods all cause rebalance storms → lag saw-tooth.

---

## 5) Cluster operations toolkit

- **Cruise Control (LinkedIn):** automated partition **rebalancing**, broker add/remove, and anomaly detection — keeps load even as the cluster grows/shrinks.
- **`kafka-reassign-partitions.sh`:** move replicas across brokers (with throttling) for scaling and repair.
- **Cruise Control / manual reassignment** on broker replacement; **rolling restarts** for upgrades (one broker at a time, wait for URP=0).
- **Cluster sizing:** account for **replication traffic** (RF× the produce bandwidth), retention × throughput for disk, and headroom for failover (lose a broker → survivors take its load).
- **Tiered storage** (note 05) to keep broker disk small; **KRaft** for metadata scalability.

---

## 6) Monitoring — the vitals to page on

| Signal | Healthy | Meaning if bad |
| --- | --- | --- |
| `UnderReplicatedPartitions` | **0** | a broker/replica is behind → durability at risk |
| `OfflinePartitionsCount` | **0** | partitions with no leader → unavailable |
| `ActiveControllerCount` (cluster) | **exactly 1** | 0 or >1 = split-brain/no brain |
| ISR shrink/expand rate | low/stable | flapping replicas, network/disk issues |
| **Consumer lag / time-lag** | within SLA | consumers falling behind (note 02) |
| request latency (produce/fetch) p99 | stable | broker overload / GC / disk |
| disk usage & log flush | headroom | approaching full → outages |
| rebalance rate | low | flapping consumers |

Ship JMX → Prometheus/Grafana (or use managed dashboards). **Page on**: URP>0, offline>0, controller≠1, lag SLA breach, disk near-full.

---

## 7) Security

- **Encryption in transit:** TLS for client↔broker and broker↔broker (mTLS).
- **Authentication:** **SASL** (SCRAM, OAUTHBEARER/OIDC, Kerberos/GSSAPI, or mTLS).
- **Authorization:** **ACLs** per topic/group/transactional-id (least privilege); or RBAC in managed platforms.
- **At rest:** disk/volume encryption; secrets externalized (not in configs); audit access to PII topics; govern schemas (note 05).

---

## 8) End-to-end: standing up a durable topic

```
① Design   topic "payments" — peak 200 MB/s, need 12-way consumer parallelism
           -> partitions = 12, RF = 3, min.insync.replicas = 2
           -> key = accountId (ordering per account, even spread)
② Producers acks=all, idempotence=on, lz4, linger=20ms
③ Consumers cooperative-sticky + static membership; max.poll.interval sized to work
④ Placement broker.rack per AZ; unclean.leader.election=false
⑤ Observe  Grafana: URP, offline, controller=1, lag/time-lag, p99, disk
⑥ Operate  Cruise Control rebalances as brokers are added; rolling upgrades (URP=0 between)
⑦ Scale    disk pressure -> tiered storage to S3; more load -> add brokers + reassign
⑧ DR       MirrorMaker 2 to a second region (active-passive)
```

---

## 9) Key takeaways

- **Partition count** is the highest-leverage choice (parallelism/ordering/rebalance cost) — over-provision slightly; adding partitions later breaks per-key ordering.
- The durable trio is **`RF=3` + `min.insync.replicas=2` + `acks=all`** with **`unclean.leader.election=false`** and rack-aware placement.
- Tune **batching/compression** for throughput; size **`max.poll.interval.ms`** to avoid rebalance-induced lag.
- Cut rebalance pain with **cooperative-sticky assignor + static membership**; automate balance with **Cruise Control**.
- **Monitor** URP, offline partitions, `ActiveControllerCount==1`, and **consumer lag**; page on these.
- **Secure** with TLS + SASL + ACLs; scale storage with **tiered storage**; do **DR** with MirrorMaker 2.

---

## 10) Quick glossary

- **Partition count:** parallelism/ordering unit; hard to change safely later.
- **`replication.factor` / `min.insync.replicas`:** copies / min in-sync copies for a write.
- **`acks=all`:** producer waits for all ISR.
- **Unclean leader election:** electing an out-of-sync replica (data-loss risk) — keep off.
- **Under-replicated partitions (URP):** replicas behind the leader.
- **`ActiveControllerCount`:** must equal 1 cluster-wide.
- **Cooperative-sticky assignor:** incremental rebalancing.
- **Static membership:** avoids rebalance on quick restarts.
- **Cruise Control:** automated cluster rebalancing/ops.
- **`broker.rack`:** rack/AZ-aware replica placement.
- **MirrorMaker 2:** cross-cluster/region replication.

---

## 11) Sources & further reading

- Apache Kafka — *Operations* (sizing, reassignment, rebalancing): <https://kafka.apache.org/documentation/#operations>
- Apache Kafka — *Broker & topic configs* (durability knobs): <https://kafka.apache.org/documentation/#configuration>
- Confluent — *Optimizing & tuning (throughput, latency, durability, availability)*: <https://docs.confluent.io/cloud/current/client-apps/optimizing/index.html>
- Confluent — *How to choose the number of partitions*: <https://www.confluent.io/blog/how-choose-number-topics-partitions-kafka-cluster/>
- LinkedIn — *Cruise Control for Apache Kafka*: <https://github.com/linkedin/cruise-control>
- KIP-429 — *Incremental cooperative rebalancing*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-429%3A+Kafka+Consumer+Incremental+Rebalance+Protocol>
- KIP-345 — *Static membership*: <https://cwiki.apache.org/confluence/display/KAFKA/KIP-345%3A+Introduce+static+membership+protocol+to+reduce+consumer+rebalances>
- Apache Kafka — *Security (TLS, SASL, ACLs)*: <https://kafka.apache.org/documentation/#security>
