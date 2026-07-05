# Geospatial Fundamentals & Spatial Databases — Detailed Notes

> Companion deep-dive for the summary diagram: `maps-geospatial-fundamentals-spatial-db-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *how* a transport/food app turns raw GPS into a searchable map, *which* spatial index (geohash, quadtree/S2, H3, R-tree) makes "find nearby drivers" fast, and *what kind of database* (SQL/PostGIS, NoSQL, in-memory spatial) is used for hot location data vs. cold persistence.

---

## 1) The one problem underneath every ride/delivery app

Every marketplace (Uber, Ola, Rapido, Namma Yatri, Swiggy, Zomato, DoorDash) reduces to the same core query, executed millions of times per second:

> *"Given a point (lat, lng), find the available supply (drivers / delivery agents / restaurants) within radius R, ranked by real travel time."*

Two facts make this hard:

- **Supply moves.** A driver emits a new location every **2–5 seconds**. With ~10M drivers that is on the order of **1–2 million location writes per second** globally, and Uber has publicly framed the "find nearby driver" read path at **1M+ requests/second**.
- **Earth is a sphere, not a grid.** Latitude/longitude are angles; a naive `WHERE distance(...) < R` forces a full scan and an expensive trig call per row. You need a way to turn 2-D geography into a **1-D sortable key** or a **tree** so an index can prune the search.

The whole domain is the engineering of that pruning.

---

## 2) Coordinates → why you can't just query lat/lng directly

- A location is `(latitude ∈ [-90, 90], longitude ∈ [-180, 180])`, plus optionally `accuracy`, `heading`, `speed`, `timestamp`.
- "Distance" on a sphere is the **great-circle (haversine)** distance, not Euclidean.
- Scanning every driver and computing haversine is `O(N)` per query — fine for a demo, fatal at city scale. **Spatial indexing** exists to convert the 2-D nearest-neighbour problem into an indexed lookup.

The two classic index families:

| Family | Idea | Examples |
| --- | --- | --- |
| **Space-filling curve** (grid → 1-D key) | Chop the world into cells, give each a string/integer ID; nearby points share ID prefixes | **Geohash**, **S2**, **H3** |
| **Tree** (recursive spatial partition) | Recursively split space; descend the tree to prune | **Quadtree**, **R-tree**, **k-d tree**, **GiST** |

---

## 3) Geohash — the base-32 space-filling curve

- Interleaves latitude/longitude bits and Base-32 encodes them into a short string, e.g. `tdr1y`.
- **Prefix property:** the longer the shared prefix, the closer two points are. `tdr1` is a box; `tdr1y` is a smaller box inside it.
- Precision by length: ~5 chars ≈ **~4.9 km × 4.9 km**; each extra char shrinks the cell ~8×.
- Powers **Redis GEO** (`GEOADD`/`GEOSEARCH`) under the hood (52-bit geohash inside a sorted set).
- **Weakness — the "edge" problem:** two points can be metres apart but sit in adjacent boxes with *different* prefixes (e.g. across the equator or prime meridian). Radius queries therefore must also scan the **8 neighbour cells**, and cell aspect ratio distorts near the poles.

---

## 4) Quadtree & S2 — square hierarchical cells

- **Quadtree:** recursively divides a square region into 4 quadrants until each leaf holds ≤ K points. Great for *skewed* density (dense downtown vs empty highway) because it subdivides only where needed. The classic textbook answer for "index moving 2-D points."
- **Google S2:** projects the sphere onto the 6 faces of a **cube**, then lays a **quadtree per face** and orders cells along a **Hilbert space-filling curve** → each cell is a 64-bit `CellId`. 31 levels; a cell can range from cm² to km².
  - Hilbert ordering keeps neighbours close in the 1-D key (better locality than plain geohash).
  - **Lyft** shards its driver-location Redis by **S2 level-5 cells (~1 km²)** so no single shard (city block) gets too hot, and uses S2 on top of OSM for map data too.
  - **Downside for gradients:** a square cell has **4 edge-neighbours at distance 1 and 4 diagonal neighbours at √2** — two different neighbour distances — which distorts "expand outward by one ring" logic.

---

## 5) H3 — Uber's hexagonal hierarchical index (the modern default)

Uber built and open-sourced **H3** specifically for marketplace pricing, dispatch, and analytics.

- **Hexagons, projected from an icosahedron.** Every `(lat, lng)` maps deterministically to exactly one **64-bit** hex ID at a chosen **resolution 0–15** (16 levels). Conversion is a **stateless math operation (microseconds, no DB lookup)**.
- **Why hexagons:** a hexagon has **one** neighbour distance (all 6 neighbours equidistant), versus 2 for squares and 3 for triangles. That uniformity makes "expand the search by one ring" and surge-gradient smoothing clean and isotropic.
- **Hierarchy (aperture 7):** each cell subdivides into ~7 children; a cell has ~1/7 the area of its parent. `compact`/`uncompact` trade cell count for resolution (e.g. 10,633 res-6 cells → 901 mixed-resolution cells).
- **The 12 pentagons:** you can't perfectly tile a sphere with hexagons, so every resolution has exactly **12 pentagons** (centred on icosahedron vertices, usually parked over ocean). Cell area also varies up to ~2× across a resolution, so for exact distances use `greatCircleDistance`, not the average edge length.
- **Resolutions used in practice:** res-**9** (~0.105 km², edge ~174 m) for **driver indexing**; res-**7** (~5.16 km², edge ~1.22 km) for **surge/pricing** buckets. Res-0 has 122 base cells (110 hexagons + 12 pentagons).

Core API (v4 names):

```js
import { latLngToCell, gridDisk, cellToParent, greatCircleDistance } from "h3-js";

const cell      = latLngToCell(12.9716, 77.5946, 9);   // point -> res-9 hex id
const neighbors = gridDisk(cell, 1);                    // "k-ring": this cell + 6 around it
const surgeCell = cellToParent(cell, 7);                // roll up to res-7 pricing bucket
```

**How "find nearby drivers" actually runs with H3:**

```
1. driver GPS -> latLngToCell(res 9)   (µs, no DB)   -> stored in an in-memory set per hex
2. driver crosses a hex boundary       -> cheap: move id from old set to new set
3. rider taps -> latLngToCell(res 9)   -> gridDisk(k≈7) -> a few dozen candidate hexes
4. union the driver sets in those hexes -> small candidate set (dozens, not thousands)
5. expensive road-network ETA runs ONLY on that candidate set (see note 02)
```

H3 does **not** measure road distance or pick the winner — it **shrinks the search space** so the costly routing runs on a handful of drivers instead of a whole city. (This is exactly what a DB index does for a table scan.)

---

## 6) R-tree / GiST — the tree behind spatial SQL

- **R-tree** groups nearby objects into hierarchical **minimum bounding rectangles (MBRs)**; a query descends only the boxes that overlap the search window. Ideal for polygons and range/`intersects` queries.
- **PostGIS** (the Postgres extension) implements this via **GiST** (Generalized Search Tree) indexes and functions like `ST_DWithin`, `ST_Distance`, `ST_Contains`. It's the gold standard for **rich, precise** geospatial SQL: zones, service-area polygons, geofences, isochrones.
- **Tile38** (open-source, Redis-RESP protocol, in-memory) keeps one **B-tree + R-tree per collection** — `O(log n)` point updates — and adds real-time **geofencing** (`Nearby`, `Within`, `Intersects`, plus roaming geofences via the `FENCE` keyword) with webhooks/pub-sub. Comfortably ~**100K+ ops/sec** on modest hardware.

---

## 7) What database goes where (the tiering that matters)

There is **no single database**. Real systems tier by access pattern:

| Layer | Purpose | Typical tech | Why |
| --- | --- | --- | --- |
| **Hot live location** (write-heavy, TTL) | current position of every active driver; nearby lookups | **Redis GEO / Redis Cluster**, **Tile38** | in-memory absorbs 1–2M writes/s; auto-expire stale pings; ms proximity queries |
| **Spatial reference / polygons** | zones, geofences, service areas, precise queries | **PostGIS (Postgres + GiST)** | ACID, rich `ST_*` functions, exact geometry |
| **Map / graph data** | road network, tiles, map elements | **DynamoDB / Docstore / object store**, keyed by S2/H3 | serialized blobs fetched by cell id (Lyft's `MapAttributes`) |
| **Trip / order state** | durable business records | **MySQL / Postgres**, **Cassandra**, **DynamoDB** | OLTP correctness + horizontal scale |
| **Cold analytics** | history, ML, dashboards | **HDFS / S3 data lake**, **Apache Pinot**, warehouse | cheap at PB scale; H3-indexed OLAP (see note 05) |

**SQL vs NoSQL vs spatial — the honest answer:**

- **SQL/PostGIS** → when you need **precision + complex geometry + transactions** (polygons, "is this point in this delivery zone?").
- **NoSQL (Cassandra/DynamoDB)** → when you need **massive, horizontally-scaled writes** for trip/location history keyed by id or cell (but raw 2M writes/s of GPS to DynamoDB on-demand would cost >$200k/day — so you **don't** put live pings there directly).
- **In-memory spatial (Redis/Tile38)** → the actual home of **live moving objects**: write-over-memory instead of reallocating, TTL expiry (`ZREMRANGEBYSCORE` to drop drivers silent >3–5 s), no global write lock because it's sharded by cell.

> Rule of thumb: **grid/geohash/S2/H3 = the index**; **Redis/Tile38 = the hot store**; **PostGIS = precise geometry**; **Cassandra/DynamoDB/lake = durable + analytics**. One app uses several at once.

---

## 8) End-to-end: a location write and a nearby read

```
WRITE (every 2-5s, ~1-2M/s):
 driver app --GPS--> gateway --> Location Service
   -> latLngToCell(res9)  (H3)   -> Redis/Tile38 set for that hex (overwrite + TTL)
   -> also emit to Kafka          -> analytics / surge / history (see notes 03 & 05)

READ (rider taps, ~1M/s):
 rider app --lat/lng--> Location Service
   -> latLngToCell(res9) -> gridDisk(k) -> candidate hex ids
   -> union driver sets from those hexes (Redis GEOSEARCH / Tile38 NEARBY)
   -> ~dozens of candidates -> hand to Matching + ETA (note 02)
```

---

## 9) Reliability / security / ops lens

- **Reliability:** live-location store is a **cache, not source of truth** — it can be rebuilt from the Kafka stream. Replicate Redis (leader/follower); expect and tolerate a stale ping.
- **Scaling:** shard by **cell id** (S2 level-5 / H3), never by raw city, to avoid a hot downtown shard. Aggregate/batch pings before persisting to cut write amplification.
- **Security/privacy:** precise location is sensitive PII — encrypt in transit (TLS/QUIC), restrict raw-trace access, **coarsen resolution** for anything user-facing or exported, and honour retention limits.
- **Observability:** watch ping ingest rate, nearby-query p99, cell hotspot skew, Redis memory/eviction, and stale-driver ratio (see note 05).

---

## 10) Key takeaways

- Every ride/delivery app is one hot query — **"nearby available supply"** — run ~1M+ times/sec; **spatial indexing** is what makes it cheap.
- **Geohash → S2/quadtree → H3** are three ways to turn 2-D geography into a sortable cell id; **R-tree/GiST** is the tree used by spatial SQL.
- **H3 (hexagons, 64-bit, 16 resolutions)** is the modern default because all neighbours are equidistant — clean k-ring radius search and surge gradients; res-9 for drivers, res-7 for surge.
- The index only **shrinks the candidate set**; precise road-network ETA runs afterwards on the survivors.
- There is **no single DB**: Redis/Tile38 for hot live location, PostGIS for precise polygons, Cassandra/DynamoDB for durable state, lake/Pinot for analytics.
- Live GPS goes to **in-memory + a stream**, never straight into an expensive per-write OLTP store.

---

## 11) Quick glossary

- **Spatial index:** structure that turns 2-D geography into a prunable key/tree so nearby lookups skip a full scan.
- **Geohash:** Base-32 string cell id; shared prefix ⇒ proximity.
- **S2:** Google's cube-face + Hilbert-curve 64-bit cell id (square cells, 31 levels).
- **H3:** Uber's hexagonal hierarchical 64-bit index (16 resolutions).
- **k-ring / `gridDisk`:** a cell plus all cells within grid-distance *k* — an approximate circle.
- **Quadtree / R-tree / GiST:** recursive space-partitioning trees; R-tree/GiST back PostGIS.
- **PostGIS:** spatial extension of Postgres (precise geometry, `ST_*`).
- **Redis GEO / Tile38:** in-memory spatial stores for hot moving objects.
- **Great-circle distance:** true distance between two points on a sphere.

---

## 12) Sources & further reading

**H3 & hexagonal indexing**
- Uber Engineering — *H3: Uber's Hexagonal Hierarchical Spatial Index*: <https://www.uber.com/en-US/blog/h3/>
- H3 project docs — *Overview / DGGS, icosahedron, pentagons, aperture 7*: <https://github.com/uber/h3/blob/master/docs/core-library/overview.md>
- H3 API reference (`latLngToCell`, `gridDisk`, resolutions table): <https://h3geo.org/docs/>

**S2, quadtrees, geohash**
- Google S2 Geometry library overview: <http://s2geometry.io/about/overview>
- Redis — *Geospatial indexes* (`GEOADD`/`GEOSEARCH`): <https://redis.io/docs/latest/develop/data-types/geospatial/>
- Geohash reference: <https://en.wikipedia.org/wiki/Geohash>

**Spatial databases**
- PostGIS docs — *Spatial indexing (GiST), `ST_DWithin`*: <https://postgis.net/docs/using_postgis_dbmanagement.html>
- Tile38 — *Ultra-fast geospatial database & geofencing*: <https://tile38.com/> and <https://github.com/tidwall/tile38>

**Systems using them**
- Lyft Engineering (via System Design newsletter) — *Redis + S2 level-5 sharding for driver location*: <https://newsletter.systemdesign.one/p/lyft-engineering>
- Lyft Engineering — *Using client-side map data (S2 cells + DynamoDB MapAttributes)*: <https://eng.lyft.com/using-client-side-map-data-to-improve-real-time-positioning-a382585ac6e>
- Hello Interview — *Design a ride-sharing service (write volume, geospatial store trade-offs)*: <https://www.hellointerview.com/learn/system-design/problem-breakdowns/uber>
