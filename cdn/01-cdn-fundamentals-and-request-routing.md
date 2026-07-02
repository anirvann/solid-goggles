# CDN Fundamentals & Request Routing — Detailed Notes

> Companion deep-dive for the summary diagram: `cdn-architecture-request-routing-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand what a CDN is, how it caches and serves content near users, and — most importantly — *how a request is routed* to the right edge server (anycast vs DNS/GSLB, end-user mapping), plus where **L4 vs L7** decisions happen.

---

## 1) What is a CDN?

A **Content Delivery Network** is a globally distributed fleet of **edge servers (PoPs)** that sit *in front of* your origin as a **reverse proxy**. Instead of every user reaching your one origin data center, they hit the nearest edge, which:

- serves **cached** content directly (static assets, images, video segments), and
- **proxies** cache misses and dynamic/uncacheable requests back to origin over an optimized path.

```
Without CDN:            With CDN:
user ── far ──▶ origin  user ─▶ nearby edge ─▶ (cache hit) ─▶ user
                                     │ (miss)
                                     └────────▶ origin ──▶ edge caches ──▶ user
```

**Why it exists (the "middle mile" problem):** the Internet is a loosely-coordinated patchwork of autonomous networks; most latency/loss bottlenecks are *between* networks and outside any single operator's control. Caching close to users avoids that middle-mile pain. Akamai's own network paper frames the CDN as the answer to exactly this problem.

**What it evolved into:** originally static caching, now **application/API acceleration**, **media delivery**, **edge compute**, and a full **security** stack — all on the same edge footprint.

---

## 2) Anatomy of the edge

| Layer | Role |
| --- | --- |
| **Anycast IP + BGP** | The same IP is announced from every PoP; Internet routing lands the user at the topologically nearest one. |
| **Router / ECMP** | Spreads packets for a target IP across many machines in the PoP (rudimentary L4 balancing). |
| **L4 load balancer** | Per-packet/flow steering across servers (e.g. Cloudflare's Unimog via XDP/eBPF; enables draining a box gracefully). |
| **L7 proxy / cache** | Terminates TLS, applies caching, WAF, routing rules (e.g. Cloudflare Pingora, Varnish/VCL, Fastly). |
| **Cache tiers** | Local cache → upper-tier ("shield") cache → origin. |
| **Origin** | Customer's source of truth for uncacheable/dynamic content. |

> Cloudflare publicly describes an XDP/eBPF pipeline on each edge box: router ECMP → **XDP L3 DDoS drop** → **XDP L4 load balancing** → iptables → socket dispatch. This is the "**single-pass**" idea: caching, DDoS, WAF, bot detection, TLS, and compute all happen at the *same* PoP, avoiding extra internal hops.

---

## 3) Caching: hit ratio is everything

Cache effectiveness is the whole game — a request served from cache never touches origin.

- **Standard caching:** each PoP is a direct reverse proxy to origin. A miss anywhere → origin fetch. Simple, but origins get hammered and nearby PoPs can't share.
- **Tiered caching (a.k.a. shielding):** designate some PoPs as **upper tiers**. A lower-tier miss first checks an upper tier before going to origin → more hits, fewer origin fetches, less load. (Cloudflare *Argo Tiered Cache*; Fastly *Shielding*; Akamai tiered distribution.)
- **Request collapsing:** many simultaneous misses for the same object are coalesced into **one** origin fetch (prevents "thundering herd").
- **Serve stale:** keep serving an expired object while revalidating, or when origin is down (resilience).

**Cache key + control:**
- Cacheability driven by `Cache-Control`, `Expires`, `ETag`/`Last-Modified` (revalidation), `Vary`.
- **Cache key** = what makes two requests "the same object" (URL + selected headers/cookies/query). Getting this right is critical, especially in multi-CDN (see notes 03).
- **Purge/invalidation:** tag-based or URL purges push new content globally (Fastly advertises instant global purge in ~150 ms).

---

## 4) Request routing — the core question

"How does the user reach the *right* edge server?" There are two dominant mechanisms, and big CDNs combine them.

### 4a) DNS-based routing / GSLB (GeoDNS)

**GSLB = Global Server Load Balancing.** An authoritative DNS server returns *different* IPs to different resolvers based on policy: geography, ASN, measured latency/RTT, weighted capacity, and **health checks**.

```
user ▶ resolver ▶ authoritative DNS (GSLB)
                     │ picks nearest healthy region/pool
                     ▼
             returns IP of best edge cluster
```

- **Pros:** simple, cheap, no special network; scales to billions of queries; works without BGP.
- **Cons:** **failover is slow** — bounded by DNS **TTL** and resolver caching. Even 30–60 s TTLs are often ignored by ISPs, pinning users to a dead region for minutes. Only *new* lookups are affected; existing TCP connections stay put.

**Akamai's mapping system** is the canonical GSLB: it builds topology + real-time health maps and resolves in two steps —
1. **Map to cluster** (top-level map → best edge *cluster* for a class of users), then
2. **Map to server** (low-level map → a specific server in that cluster).

**End-user mapping (EDNS0 Client Subnet):** classic GSLB only sees the *resolver's* IP, which may be far from the user (think public 8.8.8.8). Akamai's **end-user mapping** uses the **EDNS0 client-subnet** extension so the resolver forwards the client's `/24` prefix, letting the CDN map the *actual user*. Measured wins in Akamai's rollout: ~8× shorter mapping distance, ~2× lower RTT/download time, ~30% better time-to-first-byte — at the cost of ~8× more DNS queries.

### 4b) Anycast routing

**One IP announced from many PoPs via BGP.** Routers everywhere pick the topologically closest path; the user just "arrives" at the nearest PoP.

- **Pros:** **sub-second failover** — when a PoP withdraws its BGP route, traffic reconverges in seconds with *no DNS TTL delay*. The edge can then make **L7 (HTTP-aware)** decisions: header-based routing, consistent hashing, TLS session reuse.
- **Cons:** you must operate a global network + BGP; needs 24/7 route-anomaly ops.
- **Used by:** Cloudflare, Fastly, Google Cloud CDN (heavily anycast). Akamai and (historically) CloudFront lean more on DNS mapping.

### 4c) They combine (the real world)

A very common pattern: **GeoDNS returns a regional anycast pool**, then **anycast + L4/L7 pick the exact PoP and server within the region**. Layered failover = *defense in depth*:

```
DNS GSLB      → site/region-level failover (coarse, TTL-bound)
BGP anycast   → PoP-level failover (seconds, no DNS)
L4 LB         → load-balancer/box failover in-PoP
L7 proxy      → per-request routing, retries, health of app servers
```

| | DNS GSLB / GeoDNS | Anycast |
| --- | --- | --- |
| Steering signal | Resolver/client subnet, geo, RTT, weight | BGP path length |
| Failover speed | 30–60 s+ (TTL/caching) | Sub-second (route withdrawal) |
| Granularity | Region/cluster | Nearest PoP |
| Per-request control | No (name→IP only) | Yes (L7 at edge) |
| Infra cost | Low | High (own network + BGP) |

---

## 5) L4 vs L7 routing — where each lives

CDNs use **both**, at different points ("most production stacks use both").

| | **L4 (transport)** | **L7 (application)** |
| --- | --- | --- |
| Sees | IP + port, TCP/UDP flow | Full HTTP: host, path, headers, cookies, TLS SNI |
| Decisions | Forward/hash packets, spread flow across servers | Path/host routing, caching, WAF, auth, rate-limit, retries |
| Where in CDN | Router ECMP + XDP/eBPF LB (e.g. Unimog); **DDoS absorption tier** | Edge proxy/cache (e.g. Pingora, Varnish/VCL, Fastly) |
| Strength | Raw throughput, protocol-agnostic, volumetric DDoS drop | Rich, content-aware control + observability |

Rule of thumb: **L4 for throughput and absorbing attacks; L7 for smart, per-request behavior.** Example public stack: **Cloudflare runs Unimog (L4, XDP) in front of Pingora (L7)**; AWS users often put **NLB (L4) in front of ALB/Envoy (L7)**.

---

## 6) End-to-end flow (cache hit vs miss)

```
1. user types URL
2. DNS resolves → (GSLB picks region) → anycast IP
3. BGP routes packets to nearest PoP
4. router ECMP + XDP L4 LB → an edge server
5. edge terminates TLS (L7); runs DDoS/WAF/bot checks
6. cache lookup by cache key
      ├─ HIT  → serve from edge  ✅ (origin never touched)
      └─ MISS → check upper-tier (shield)
                  ├─ HIT → fill local cache → serve
                  └─ MISS → optimized route to origin
                             → store in cache → serve
7. response returns via same PoP to user
```

**Risks per step:** wrong cache key → low hit ratio; DNS TTL too high → slow failover; no shield → origin overload; no request-collapsing → thundering herd on popular misses.

---

## 7) Reliability & operations lens

- **Anycast + stateless L4** → sub-second global failover; **withdraw BGP route** to drain a PoP.
- **Traffic manager**: continuously probe PoPs and move traffic away from CPU-overloaded/congested data centers (Cloudflare Traffic Manager).
- **Tiered cache / shield** protects the origin and improves hit ratio.
- **Serve-stale + request-collapsing** keep you up during origin trouble and spikes.
- **What to monitor:** cache hit ratio, origin offload %, edge/origin RTT & TTFB, 5xx rate, PoP CPU, BGP route health, DNS query volume (esp. with end-user mapping).

---

## 8) Key takeaways

- A CDN is a **global reverse-proxy cache**: serve near the user, offload the origin, optimize the middle mile.
- **Routing = DNS/GSLB (coarse, TTL-bound) + anycast (fine, sub-second).** Big CDNs layer both.
- **GSLB** picks *region/cluster*; **end-user mapping (EDNS0)** makes DNS routing accurate for public resolvers.
- **L4** absorbs and spreads packets (DDoS tier); **L7** does content-aware routing, caching, security — same PoP, single pass.
- **Cache hit ratio** is the primary performance lever; tiered caching, request collapsing, and serve-stale protect the origin.

---

## 9) Quick glossary

- **PoP / edge:** point-of-presence data center running edge servers.
- **Anycast:** one IP announced from many locations; BGP picks nearest.
- **GSLB:** Global Server Load Balancing — DNS-layer geo/health/latency steering.
- **EDNS0 Client Subnet (ECS):** DNS extension exposing the client's subnet to the CDN for accurate mapping.
- **Shield / upper tier:** designated cache in front of origin to boost hit ratio.
- **Request collapsing:** coalescing concurrent identical misses into one origin fetch.
- **TTFB:** time to first byte.

---

## 10) Sources & further reading

**How CDNs / edges work**
- Cloudflare — *CDN Reference Architecture*: <https://developers.cloudflare.com/reference-architecture/architectures/cdn/>
- Cloudflare — *Architecture and how BPF eats the world* (XDP/eBPF, L3/L4 pipeline): <https://blog.cloudflare.com/cloudflare-architecture-and-how-bpf-eats-the-world/>
- Cloudflare Learning — *What is a CDN?*: <https://www.cloudflare.com/learning/cdn/what-is-a-cdn/>
- Akamai — *The Akamai Network: a platform for high-performance Internet applications* (PDF): <https://courses.cs.duke.edu/spring23/compsci512/papers/akamai-cdn.pdf>

**Request routing / GSLB / anycast / mapping**
- Akamai / SIGCOMM 2015 — *End-User Mapping: Next Generation Request Routing* (PDF): <https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p167.pdf>
- Akamai — *End-User Mapping* technical publication: <https://www.akamai.com/site/en/documents/research-paper/end-user-mapping-next-generation-request-routing-for-content-delivery-technical-publication.pdf>
- *DNS-based GSLB vs Anycast Edge Proxy*: <https://www.systemoverflow.com/learn/load-balancing/global-load-balancing/dns-based-gslb-vs-anycast-edge-proxy>
- *Anycast vs GeoDNS: how CDNs route users to the right PoP*: <https://speedtesthq.com/guides/cdn/anycast-vs-geodns>
- Cloudflare — *What is anycast?*: <https://www.cloudflare.com/learning/cdn/glossary/anycast-network/>

**L4/L7 load balancing**
- The HLD Handbook — *Load Balancers* (L4 vs L7, Unimog/Pingora, anycast failover): <https://hld.handbook.academy/curriculum/building-blocks/load-balancers/>
- Cloudflare — *Unimog: edge load balancing*: <https://blog.cloudflare.com/unimog-cloudflares-edge-load-balancer/>

**Tiered cache**
- Cloudflare — *Argo Smart Routing / Tiered Cache* (in Reference Architecture, above)
- Fastly — *Shielding*: <https://www.fastly.com/documentation/guides/concepts/shielding/>
