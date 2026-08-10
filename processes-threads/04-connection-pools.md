# Connection Pools — Detailed Notes

> Companion deep-dive for the summary diagram: `connection-pools-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand why connection pools exist, how they relate to **threads and processes**, what resources they conserve, and how to size them so you avoid connection storms and context-switch collapse.

---

## 1) Big picture — what is a connection pool?

A **connection pool** is a cache of **already-established** connections (usually to a database, but also Redis, HTTP backends, etc.) that application code **borrows**, uses, and **returns** instead of `connect()` / `close()` per request.

```
Without pool (per request):
  request → TCP+TLS+auth → query → close     ← expensive, floods server

With pool:
  startup → open N connections once
  request → borrow → query → release          ← reuse
```

**Where it fits:** between your app’s request handlers (threads/async tasks) and a server that has a **hard limit** on concurrent connections — e.g. PostgreSQL `max_connections`, each backed by a **process**.

---

## 2) Why connections are expensive (resource lens)

Opening a DB connection typically costs:

| Step | What you pay |
| --- | --- |
| TCP handshake | RTT(s) |
| TLS handshake | CPU + more RTTs |
| Auth / session setup | CPU + catalog loads |
| Server-side session | **Memory + a process or thread** on the DB |

**PostgreSQL specifically:** roughly **one backend process per connection**. Each holds RAM (buffers, `work_mem` potential), file descriptors, locks, and is a schedulable task. Hundreds of mostly-idle connections still hurt: RAM, lock tables, and — when they wake — **context switches**.

So a pool protects two sides:

1. **Client latency** — skip setup per request  
2. **Server stability** — cap concurrent backends / sessions  

---

## 3) How pools interact with threads & processes

### Pattern A — thread-per-request + pool (classic Java / HikariCP)

```
HTTP threads  t1 t2 t3 t4 t5 … t100
                 \  |  |  /
                  ╲ | │ ╱
               [ connection pool  size=20 ]
                      │
                 PostgreSQL (≤20 backends)
```

- Many **threads** share few **connections**.
- A thread **blocks** while holding a connection (typical JDBC).
- Pool size ≪ thread count → queue for a connection (admission control). Good.

### Pattern B — process workers (prefork) + pool

```
Unicorn/Gunicorn workers (processes) each with pool_size=5
  10 workers × 5 = 50 DB connections
```

Watch **multiplicative explosion**: instances × pool_size.

### Pattern C — external pooler (PgBouncer) multiplexes

```
Many app processes/threads
        │
        ▼
   PgBouncer (one process, event loop)
        │  transaction / statement pooling
        ▼
   Few Postgres backends
```

Apps may still use a small in-process pool (HikariCP) **and** PgBouncer in front of Postgres — common in microservices.

| Layer | Lives in | Role |
| --- | --- | --- |
| **HikariCP / JDBC pool** | App JVM | Fast local reuse; limits connections **from this process** |
| **PgBouncer / Odyssey** | Sidecar / shared service | Multiplex many client sessions → few DB backends; protects DB across **all** apps |

---

## 4) Pool mechanics — end-to-end borrow flow

```
1. App needs DB
2. pool.acquire()
     ├─ idle conn available → hand out
     ├─ below max → create new (TCP+auth)
     └─ at max → wait (timeout) or fail
3. Thread/task runs queries on that conn
4. pool.release() → back to idle (or validate/evict)
5. Idle reaper closes surplus after idleTimeout
```

| Step | Risk | Mitigation |
| --- | --- | --- |
| Acquire wait | Thread pile-up, latency | Size pool + app concurrency together; fail fast |
| Leak (never release) | Pool exhaustion | `try/finally`, pool leak detection |
| Stale connection | Errors after firewall idle drop | Validation query / TCP keepalive |
| Oversize pool | DB CPU/RAM thrash, CS storm | Cap near cores; use external pooler |

### Lucid mini-example (pseudocode)

```python
# BAD
def handle(req):
    conn = psycopg2.connect(...)   # handshake every time
    try:
        return query(conn, req)
    finally:
        conn.close()

# GOOD
pool = ConnectionPool(min=2, max=20)

def handle(req):
    with pool.connection() as conn:  # borrow / release
        return query(conn, req)
```

---

## 5) Sizing — Little’s Law + PG knee

**Little’s Law (steady state):**

\[
L = \lambda \times W
\]

- \(L\) ≈ connections you need in use  
- \(\lambda\) = requests/sec that need the DB  
- \(W\) = mean hold time (query + transaction time)

Example: 500 req/s × 20 ms hold = **10** busy connections. Pool of 40 might be enough headroom; pool of 200 is usually waste.

**PostgreSQL wiki starting point for active backends:**

```text
≈ (CPU cores × 2) + effective_spindle_count
```

(spindles ≈ 0 if data is cached in RAM). Then **benchmark** — the wiki stresses the “knee”: more connections past saturation **reduce** TPS due to contention and context switches.

**Multi-instance math:**

```text
total_db_conns ≈ sum(app_instances × pool_size)   # without PgBouncer
               ≈ pgbouncer_pool_size               # with transaction pooling
```

---

## 6) Pooling modes (PgBouncer)

| Mode | Holds server conn until | Good for | Breaks |
| --- | --- | --- | --- |
| **Session** | Client disconnects | Compatibility | Weak multiplexing |
| **Transaction** | End of transaction | Web apps | Some session features (`SET`, prepared stmts — need care) |
| **Statement** | End of statement | Extreme multiplexing | Multi-statement transactions |

---

## 7) Reliability / security / ops checklist

- [ ] `max_connections` on DB > peak pooled backends + admin slots  
- [ ] Timeouts: connect, acquire, query, idle  
- [ ] Metrics: pool active/idle/pending, wait time, create/destroy rate  
- [ ] Alerts on pool exhaustion and acquire latency  
- [ ] Secrets not logged; TLS to DB; rotate passwords without dumpstering pool wrongly  
- [ ] On deploy: drain / warm pools; avoid thundering herd reconnect  
- [ ] Prefer **queue work** over opening more connections when saturated  

---

## 8) Key takeaways

- Pools **reuse** expensive connections and **cap** concurrent server sessions.
- They sit at the intersection of **threads/processes** (who borrow) and **DB processes** (who serve).
- Oversize pools cause the same pain as too many threads: RAM, locks, **context switches**.
- Size with measured latency × QPS; use an external pooler when many app instances multiply connections.
- Always release connections; treat leaks like deadlocks.

---

## 9) Quick glossary

- **Borrow/release:** check-out / check-in of a pooled connection.  
- **Pool exhaustion:** all connections checked out; new acquirers block or fail.  
- **Transaction pooling:** return server connection to the pool after each transaction.  
- **Connection storm:** mass simultaneous reconnect (deploy, blip) overwhelming the DB.  
- **Backend:** PostgreSQL server process handling one connection.

---

## Sources & further reading

- [Number Of Database Connections — PostgreSQL Wiki](https://wiki.postgresql.org/wiki/Number_Of_Database_Connections) (knee, context switches, sizing formula)
- [PgBouncer documentation](https://www.pgbouncer.org/)
- [HikariCP](https://github.com/brettwooldridge/HikariCP) — widely used JVM pool
- [Connection Pool Sizing with Little’s Law — Michal Drozd](https://www.michal-drozd.com/en/blog/connection-pool-littles-law/)
- [clone(2) / process model background](https://man7.org/linux/man-pages/man2/clone.2.html) — why each PG connection is a heavyweight task
