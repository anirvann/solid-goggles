# Map Creation, Maintenance & the Routing Graph — Detailed Notes

> Companion deep-dive for the summary diagram: `maps-creation-maintenance-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *how the map itself is created and kept fresh* — fusing OpenStreetMap + government data + GPS probe traces + satellite imagery — how noisy GPS is **map-matched** onto the road graph (HMM + Viterbi), and how that graph is turned into a **routing engine** (Contraction Hierarchies) fast enough to score dispatch ETAs.

---

## 1) A "map" is really two artifacts

When engineers say "the map," they mean two very different products built from the same data:

| Artifact | What it is | Used by |
| --- | --- | --- |
| **Render tiles** | tiles of streets, water, labels (raster images *or* vector data) | the visual map you see + pan/zoom |
| **Routing graph** | a directed graph: **nodes** (intersections) + **edges** (road segments) with attributes (length, speed, turn restrictions, one-way) | dispatch ETA, navigation, map-matching |

The routing graph is the one that matters for connecting drivers to riders — it's what the ETA/routing engine (note 02) runs on.

### Raster vs. vector tiles (how the map you see is drawn)
- The world is projected to **Web Mercator** and cut into a `{z}/{x}/{y}` tile pyramid; the client fetches only the tiles in the current viewport.
- **Raster tiles** (the original Google Maps pattern) are **pre-rendered PNG/JPEG images** — simple, but they pixelate on zoom and the style is baked in.
- **Vector tiles** (the modern default, e.g. **Mapbox Vector Tiles / MVT**) ship **protobuf-encoded geometry** (`.mvt`/`.pbf`: points, lines, polygons + attributes), *not* pixels. The client decodes them (often in worker threads) and **renders on the GPU via WebGL** (Mapbox GL / MapLibre) against a **style JSON** applied *at runtime*. That enables smooth zoom/rotate/tilt and **dynamic styling** — the same tile data becomes a light map, dark map, or fleet/logistics map by swapping the style. The routing graph and the render tiles are built from the same source data but are separate artifacts.

---

## 2) The four data sources fused into a map

Modern maps are **fused** from multiple sources, each covering the others' blind spots:

1. **OpenStreetMap (OSM) + government/authoritative datasets** — the **base geometry**: road shapes, classifications, turn restrictions, and (from gov data) posted speed limits. OSM is community-edited and published via a **daily replication feed (minutely/hourly/daily diffs)**.
2. **Vehicle probe / GPS traces** — the "ground truth of how people actually drive," gathered from tens of millions of navigating devices. Probe data reveals:
   - **new roads** (traces that consistently follow a path not in the graph),
   - **real speeds** (historical speed distributions vs. posted limits → live traffic),
   - **road conditions** (braking-event clustering).
3. **Satellite / aerial imagery** (Maxar, Planet Labs, etc.) processed through **ML change detection** to spot new construction, closures, and geometry changes.
4. **Operational feedback** — driver/rider reports, failed pickups, "no such road" errors.

These are merged in a **periodic map-data pipeline** (often a **weekly** graph rebuild) that resolves conflicts by a **source-priority hierarchy** and requires **dual confirmation** before committing a new road (two independent signals, e.g. probe + imagery), to avoid hallucinating roads from GPS noise.

> **Why this matters most in India (Zomato).** Open-source base maps are **sparse in many Indian cities** — dense older districts, makeshift roads, and inroads are missing, which wrecks graph-based routing and ETAs. Zomato runs a **map reconstruction** pipeline that leverages **delivery-partner pings + trip data** to *infer new roads, unknown roads and shortcuts*, then **filters, merges them into the India map and makes them routable**. It pairs this with **sensor fusion in the DP app** and pre/post GPS-noise filtering. This is the probe-data → road-discovery loop in action — and a reason Zomato moved ETA from a map-graph model to a tree-based one where the graph is unreliable (note 02).

---

## 3) Map-matching — snapping noisy GPS to the road graph

Raw GPS is off by **5–50 m** (urban canyons, multipath), so a ping rarely lands exactly on a road. **Map-matching** snaps a sequence of noisy points onto the most probable path in the graph. It underpins ETAs, live-tracking smoothing, trip replay, and road discovery.

- **Model: Hidden Markov Model (HMM).** Hidden states = candidate road segments near each GPS point; the algorithm finds the most likely *sequence* of segments.
  - **Emission probability:** how close a GPS point is to a candidate segment.
  - **Transition probability:** how plausible it is to drive from one candidate to the next (route distance vs. straight-line distance).
- **Solver: the Viterbi algorithm** finds the single highest-probability path (the "Viterbi path").
- **Production tooling:** **Valhalla's Meili** module and **OSRM's `/match` service** both implement HMM+Viterbi map-matching on OSM data; Google exposes a "Snap to Roads" API. (Valhalla is favored where memory is tight; OSRM for fast setup.)

```
noisy GPS trail        candidate segments per point        Viterbi best path
   • • •      -->   for each •: nearest roads (radius)  -->  one clean road path
 (off-road)         HMM: emission + transition probs        (snapped to graph)
```

---

## 4) The routing engine — from graph to sub-millisecond routes

Dispatch scores many `(rider, driver)` ETAs per batch (note 02), so route queries must be **< 1 ms**. Plain Dijkstra/A* over a continental graph is far too slow, so production engines **preprocess** the graph.

### Contraction Hierarchies (CH) — the production algorithm
Used by **OSRM, Valhalla, and Google Maps**.

- **Offline preprocessing:** rank nodes by "importance"; **contract** low-importance nodes one by one, adding **shortcut edges** that preserve shortest-path distances. This builds a hierarchy.
- **Query time:** a **bidirectional search** that only ever moves *up* the hierarchy explores just **~hundreds of nodes total**, regardless of route length → **< 1 ms** even for country-scale graphs. This is what makes it viable to call routing inside a dispatch batch.
- Engines also produce alternatives, isochrones, distance matrices, and vector tiles from the same graph.

### Keeping ETAs live without rebuilding the graph
- Static CH bakes edge weights, but traffic changes constantly. **Customizable Contraction Hierarchies (CCH)** separate *topology* (rebuilt weekly) from *weights* (updated cheaply).
- Live **segment speeds** from probe data land in Redis; the routing server **recomputes affected shortcut weights every ~30 s** (e.g. < 500 ms to apply 10,000 changed segments) — so ETAs reflect current traffic without a full graph rebuild.
- **DeepETA** (note 02) then applies a learned residual on top of the CH/CCH base ETA.

---

## 5) The map maintenance loop (how it stays fresh)

```
                 ┌──────────────────────────────────────────────┐
                 │  Sources                                       │
  OSM diffs ─────┤  gov data · probe/GPS traces · satellite ML    │
                 │  · operational reports                         │
                 └───────────────┬──────────────────────────────┘
                                 v
                  Map data pipeline (weekly rebuild)
                  - conflict resolve (source priority)
                  - dual-confirm new roads
                  - validate -> commit to graph DB (e.g. PostgreSQL)
                                 │
              ┌──────────────────┼───────────────────┐
              v                                       v
     Render tiles (visual map)             Routing graph (CH/CCH)
                                                     │
                                     live speeds (probe -> Redis)
                                     -> weight refresh every ~30s
                                                     │
                                     used by dispatch ETA + navigation (note 02)
```

- **Topology** (roads exist / geometry) changes slowly → **weekly** batch rebuild.
- **Weights** (current speed) change constantly → **~30 s** live updates.
- **Feedback:** probe traces from the live fleet continuously feed road discovery, closing the loop — the fleet both *uses* and *improves* the map.

---

## 6) Reliability / security / ops lens

- **Reliability:** map builds are versioned and validated; a bad build can misroute the whole fleet, so pipelines gate on **dual confirmation** and regression checks before promotion, with rollback.
- **Data quality:** GPS noise, spoofing, and one-off detours must not create phantom roads — hence probabilistic map-matching + confirmation thresholds.
- **Security/privacy:** probe traces are de-identified/aggregated before feeding road discovery; raw individual trails are restricted PII.
- **Observability:** monitor map-match success rate, ETA error (predicted vs. actual per segment), route-compute latency, stale-speed coverage, and new-road candidate precision/recall (note 05).

---

## 7) Key takeaways

- A "map" = **render tiles** (what you see) + a **routing graph** (nodes/edges) — dispatch cares about the graph.
- The visual map is increasingly **vector tiles (MVT, protobuf)** rendered client-side on the **GPU (WebGL)** against a runtime **style JSON**, not pre-baked raster images.
- Maps are **fused**: **OSM + gov data + GPS probe traces + satellite ML**, merged in a **weekly** pipeline with **conflict resolution + dual-confirm** for new roads.
- **Map-matching** snaps noisy GPS onto the graph with an **HMM solved by Viterbi** (Valhalla Meili, OSRM `/match`).
- Routing is fast because of **Contraction Hierarchies** — offline shortcuts → **< 1 ms** queries; OSRM/Valhalla/Google use it.
- **Live traffic** is applied via **CCH weight refresh (~every 30 s)** from probe speeds, then corrected by **DeepETA**.
- The fleet is a sensor: probe data both consumes and continuously **improves** the map — critical where base maps are sparse (Zomato reconstructs Indian roads from DP pings).

---

## 8) Quick glossary

- **Routing graph:** directed graph of intersections (nodes) and road segments (edges) with attributes.
- **Render tiles:** map display data cut into a `{z}/{x}/{y}` pyramid — raster (images) or vector.
- **Vector tile / MVT:** protobuf-encoded geometry (`.mvt`/`.pbf`) styled & rendered on the client (WebGL).
- **Style JSON:** runtime description of how to paint tile layers (enables dynamic light/dark/logistics styles).
- **OSM:** OpenStreetMap — community base map, published as daily diffs.
- **Probe / GPS trace:** anonymized vehicle location trails used for roads, speeds, traffic.
- **Map-matching:** snapping noisy GPS to the most probable road path.
- **HMM / Viterbi:** hidden-state model / algorithm that finds the best segment sequence.
- **Meili / OSRM `/match`:** production map-matching engines on OSM data.
- **Contraction Hierarchies (CH):** preprocessing with shortcut edges → sub-ms routing.
- **CCH:** Customizable CH — split topology (weekly) from weights (live).
- **Isochrone:** reachable area within a time budget from a point.
- **Dual confirmation:** requiring two independent signals before adding a new road.

---

## 9) Sources & further reading

**Map data & fusion**
- OpenStreetMap wiki — *Planet.osm & replication (minutely/daily diffs)*: <https://wiki.openstreetmap.org/wiki/Planet.osm>
- MapFuse (arXiv 1802.02351) — *Road-network fusion for incremental map updates (new roads, closures)*: <https://arxiv.org/abs/1802.02351>
- CrackingWalnuts — *Maps platform system design (source fusion, weekly pipeline, dual confirmation, CCH refresh)*: <https://crackingwalnuts.com/post/maps-platform-system-design>
- Zomato — *The elements of scalable machine learning (map reconstruction from DP pings, sensor fusion)*: <https://blog.zomato.com/elements-of-scalable-machine-learning>

**Render / vector tiles**
- Mapbox — *Vector tiles introduction (MVT, client-side WebGL rendering, dynamic styling)*: <https://docs.mapbox.com/data/tilesets/guides/vector-tiles-introduction/>
- Mapbox Vector Tile Specification (protobuf `.mvt`): <https://mapbox.github.io/vector-tile-spec/>

**Map-matching**
- Newson & Krumm (Microsoft Research) — *Hidden Markov Map Matching Through Noise and Sparseness* (the canonical HMM paper): <https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/>
- Valhalla — *Meili map-matching (HMM + Viterbi)*: <https://valhalla.github.io/valhalla/meili/>
- *A practical guide to open-source map-matching for big GPS data (OSRM vs. Valhalla)*: <https://link.springer.com/article/10.1007/s42979-022-01340-5>

**Routing engines & Contraction Hierarchies**
- Open Source Routing Machine (OSRM) — OSM wiki (CH / multilevel Dijkstra, <1 ms): <https://wiki.openstreetmap.org/wiki/OSRM>
- Geisberger et al. — *Contraction Hierarchies: Faster and Simpler Hierarchical Routing in Road Networks*: <https://algo2.iti.kit.edu/documents/routeplanning/geisberger_dissertation.pdf>
- Valhalla routing engine: <https://github.com/valhalla/valhalla>
