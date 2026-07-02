# CDN Security & Multi-CDN Resiliency — Detailed Notes

> Companion deep-dive for the summary diagram: `cdn-security-multicdn-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the security stack a modern CDN runs at the edge (DDoS, WAF, bot management, TLS, API security, Zero Trust) and the operational strategy of running **multiple CDNs** for resiliency — why teams do it, how traffic steering works, and the trade-offs.

---

## 1) The CDN is now a security platform

Because *every request traverses the edge as a reverse proxy*, the CDN is the natural place to enforce security **before traffic reaches origin**. The edge footprint that does caching also does DDoS scrubbing, WAF, bot detection, TLS, and API security — often in a **single pass** at the same PoP (no extra internal hops).

Modern CDN security surface (all under one contract):
- **L3/L4 + L7 DDoS mitigation**
- **WAF** (Web Application Firewall)
- **Bot management**
- **API security** (schema validation, mTLS, anomaly detection)
- **TLS/SSL termination + management**
- **Zero Trust access** (identity-aware, replaces VPN)
- **DNS security**, plus supply-chain protection (e.g. Cloudflare Page Shield for 3rd-party JS)

---

## 2) DDoS mitigation

**Goal:** absorb/scrub attack traffic at the edge so the origin never sees it.

| Layer | Attack examples | CDN defense |
| --- | --- | --- |
| **L3/L4 (volumetric)** | SYN floods, UDP floods, amplification | Drop at the edge in-kernel: Cloudflare uses **XDP/eBPF** to drop large L3 attacks *before* the normal networking stack; anycast spreads volume across many PoPs. |
| **L7 (application)** | HTTP floods, slowloris, cache-busting | Rate limiting, challenge, bot scoring, WAF rules at the L7 proxy. |

Two architectural philosophies:
- **Every PoP is a scrubbing center (Cloudflare):** anycast means volume is naturally distributed; no "detour to a scrubbing center," so **no added latency**; DDoS protection is automatic/unmetered on all plans.
- **Dedicated scrubbing centers (Akamai Prolexic):** route traffic through specialized centers for very large enterprise/network-layer attacks — deep, specialized handling.

**Anycast is itself a DDoS feature:** the same attack is split across the whole network instead of hitting one target IP/location.

---

## 3) WAF (Web Application Firewall)

Operates at **L7** and inspects HTTP requests for malicious patterns:

- **OWASP Top 10:** SQL injection (SQLi), cross-site scripting (XSS), RCE, path traversal, etc.
- **Managed rulesets** (vendor-maintained, updated as new CVEs appear) **+ custom rules** (your own logic).
- **Rate limiting** per IP/route/token.
- **Key operational metric: false-positive rate** — a WAF that blocks legitimate users creates operational noise and lost revenue. Managed rulesets need ongoing tuning as the app evolves. (Akamai advertises very low FP rates in testing; both need tuning.)

> Example: retailer Carrefour replaced five separate security tools, put 400 e-commerce sites behind a CDN WAF + Bot Management, and cut incident-resolution time ~75%.

---

## 4) Bot management

Distinguish **good bots** (search crawlers) from **bad bots** (credential stuffing, account takeover, scraping, inventory/sneaker hoarding, carding).

Techniques:
- **ML-based scoring** (Cloudflare assigns a bot score 1–99; act on thresholds; models trained on a huge fraction of Internet traffic → sees novel attacks first).
- **Device fingerprinting + behavioral biometrics** (mouse/keystroke/scroll patterns) — Akamai Bot Manager's long-standing signature database + biometrics.
- **Custom handling** via edge compute (e.g. Workers) beyond simple allow/block.
- **Account protection** layers specifically for credential stuffing / ATO.

**Why at the edge:** mitigation happens near-instantly at the PoP, stopping bots without adding latency for real humans. This ties directly to the **waiting room / inventory pre-check** pattern (notes 02): bot filtering + queueing together keep flash-sale inventory fair.

---

## 5) TLS & API security

- **TLS termination at the edge:** handshake completes at the nearest PoP (lower RTT), then a warm/secure path to origin. CDN also manages certs (issuance, rotation, SNI).
- **API security:** schema validation, endpoint discovery, **mutual TLS (mTLS)**, rate limiting, and anomaly detection on API traffic (e.g. Cloudflare API Shield). Increasingly important as traffic shifts from pages to APIs.
- **Zero Trust access:** identity-aware, least-privilege access to internal apps at the edge, replacing legacy VPNs.

---

## 6) Multi-CDN — running more than one CDN

**Yes — companies deliberately run multiple CDNs for resiliency** (and performance/cost). Historically only big media companies did this; now it's a mainstream resilience pattern, accelerated by high-profile single-vendor outages (e.g. large Cloudflare incidents in late 2025 driven by internal config changes).

### 6a) Why multi-CDN?

- **Eliminate single-vendor SPOF:** if one CDN has an outage (mechanical or cyberattack), shift traffic to another. With a single vendor, during an outage "there's nothing to do but watch the status page."
- **Performance:** different CDNs are faster in different regions/ISPs; steer each user to the best-performing network.
- **Cost:** route some traffic over "premium" infra and some over cheaper infra.
- **Regional coverage / compliance:** cover geographies one vendor serves poorly.

### 6b) Active-active vs active-passive

| | **Active-active** | **Active-passive (failover)** |
| --- | --- | --- |
| Traffic | Split across CDNs simultaneously | All to primary; switch to backup only on outage |
| Caches | **Warm on all** providers | Backup cache **cold** at switch time |
| Failover feel | Seamless, backups ready instantly | Latency/load spike when switching to cold CDN |
| Complexity | Higher | Lower |

Active-active is generally preferred for resilience because a cold backup + DNS-cache lag = a rough switchover.

### 6c) Traffic steering (the decision engine)

A **steering layer** decides which CDN serves each request, using signals: **geo/ASN, latency/throughput, real-user (RUM) or synthetic measurements, health checks, and cost**. Two implementation styles:

- **DNS-based steering:** a managed traffic-manager (NS1, Cloudflare Load Balancing, Citrix ITM, etc.) is authoritative DNS and returns the best CDN's hostname/IP per client.
  - *Limitation:* **DNS TTL + resolver caching** → failover isn't instant; ISPs may pin users to a failed CDN past your TTL. Even 60 s TTLs are often ignored. Rarely truly zero-downtime.
- **Client-side steering:** the app/player measures CDNs in real time and picks per-request/segment (common in video). Faster, more granular; needs client instrumentation.

Guard rails matter: **clear precedence rules** to avoid **oscillation** (flapping between CDNs).

### 6d) The big trade-off: cache fragmentation

Each CDN keeps its **own independent cache**. Splitting traffic across N CDNs means each sees fewer requests → **lower per-CDN hit ratio** → **more origin fetches** → higher origin load and egress cost.

Mitigations:
- **Origin shield / mid-tier cache:** a centralized caching layer between the CDNs and origin (e.g. Fastly *Media Shield*) consolidates requests, cuts origin load and egress, and prevents **thundering herd** during cache misses or failover.
- **Consistent cache keys** across all CDNs (same normalization) so objects are shared logically.
- **Synchronized purge** across every vendor (invalidate everywhere at once).
- **Unified observability:** normalize logs/metrics from each provider into one view for incident response.

```
              ┌── CDN A ──┐
users ▶ steer ┤           ├▶  Origin Shield (mid-tier cache) ▶ Origin
   (DNS/RUM)  └── CDN B ──┘        consolidates misses,
                                   prevents thundering herd
```

### 6e) Operating multi-CDN (checklist)

- Confirm multi-CDN solves a **real** requirement (don't add complexity for its own sake).
- Choose steering architecture + signals; set **precedence + guard rails**.
- Prepare origin + auth to serve **multiple** CDNs (higher fan-in, different retry/cache semantics).
- **Align security controls** (WAF/bot rules) across vendors — feature parity gaps are real.
- **Test failover and rollback**; keep TTLs short but expect resolver lag.
- Deploy monitoring/alerting tied to SLOs; run incident playbooks + post-incident reviews.

---

## 7) End-to-end flow (security + multi-CDN)

```
1. steering layer (DNS/RUM) picks best healthy CDN for this user
2. anycast → nearest PoP of chosen CDN
3. edge single-pass: L3/L4 DDoS drop → L7 WAF → bot scoring → TLS
4. cache lookup
      ├─ hit  → serve (origin untouched)
      └─ miss → origin shield (shared) → origin
5. if a CDN degrades → steering removes it from rotation (minutes via DNS;
   anycast handles intra-CDN PoP failure in seconds)
```

---

## 8) Key takeaways

- The CDN edge is a **security platform**: DDoS (L3/L4 + L7), WAF, bot management, TLS, API security, Zero Trust — enforced before origin, often single-pass.
- **DDoS:** every-PoP-scrubbing (anycast, no latency penalty) vs dedicated scrubbing centers (Akamai Prolexic). Anycast inherently disperses volumetric attacks.
- **WAF** blocks OWASP-class attacks at L7; watch the **false-positive rate**. **Bot management** uses ML scoring + fingerprinting/biometrics.
- **Yes, companies run multiple CDNs** for resiliency (avoid single-vendor outages), performance, and cost.
- Multi-CDN needs **traffic steering** (DNS or client-side) but pays a **cache-fragmentation** tax — fix with **origin shield, consistent cache keys, synchronized purge, unified observability**. Prefer **active-active** (warm caches) over cold failover.

---

## 9) Quick glossary

- **Scrubbing center:** facility that filters attack traffic (Akamai Prolexic). In anycast CDNs, *every PoP* scrubs.
- **WAF:** L7 firewall inspecting HTTP for SQLi/XSS/etc.
- **Bot score:** likelihood a request is automated (e.g. 1–99).
- **Traffic steering:** logic choosing which CDN/PoP serves a request.
- **Active-active / active-passive:** all CDNs live vs primary+backup.
- **Origin shield:** shared mid-tier cache in front of origin.
- **Cache fragmentation:** hit-ratio loss from splitting traffic across independent CDN caches.
- **Thundering herd:** many simultaneous misses hammering origin at once.

---

## 10) Sources & further reading

**CDN security (DDoS / WAF / bots)**
- Cloudflare — *Architecture & BPF* (XDP L3/L4 DDoS drop): <https://blog.cloudflare.com/cloudflare-architecture-and-how-bpf-eats-the-world/>
- Cloudflare — *Bot Management*: <https://www.cloudflare.com/products/bot-management/>
- *Cloudflare vs Akamai WAF: bot protection, DDoS* (comparison): <https://www.decryptiondigest.com/blog/cloudflare-vs-akamai-waf-comparison>
- *Cloudflare vs Akamai vs Fastly — CDN & edge security*: <https://technologymatch.com/blog/cloudflare-vs-akamai-vs-fastly-cdn-and-edge-security>
- Cloudflare Learning — *What is a WAF?*: <https://www.cloudflare.com/learning/ddos/glossary/web-application-firewall-waf/>
- Cloudflare Learning — *What is a DDoS attack?*: <https://www.cloudflare.com/learning/ddos/what-is-a-ddos-attack/>
- Akamai — *Prolexic (DDoS protection)*: <https://www.akamai.com/products/prolexic-solutions>

**Multi-CDN resiliency**
- Fastly — *Multi-CDN: a critical decision for a resilient architecture*: <https://www.fastly.com/blog/multi-cdn-critical-decision-for-resilient-architecture>
- CDN Handbook — *Multi-CDN for operators*: <https://www.cdnhandbook.com/advanced/multicdn/>
- Hydrolix — *How does a multi-CDN strategy work?*: <https://hydrolix.io/blog/how-does-multi-cdn-strategy-work/>
- Hydrolix — *Complete guide to multi-CDN*: <https://hydrolix.io/blog/multi-cdn-guide/>
- Gcore — *Multi-CDN for business continuity & resilience*: <https://gcore.com/blog/multi-cdn-business-continuity-resilience>
- The HLD Handbook — *Load Balancers* (DNS GSLB vs anycast failover): <https://hld.handbook.academy/curriculum/building-blocks/load-balancers/>
