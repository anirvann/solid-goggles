# Devices & Security Across the Layers — Detailed Notes

> Companion deep-dive for the summary diagram: `devices-across-layers-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Know which OSI layer each network device and security control operates at — hubs, switches, routers, NAT gateways, firewalls, load balancers, reverse proxies, WAFs — so you can say what each one can see, decide, and break.

---

## 1) Big picture

A device "operates at layer N" when it **reads and makes decisions on layer-N headers**. The higher the layer, the more it can see (and the more it costs to process).

| Device | Highest layer it reads | Decides based on | Typical job |
| --- | --- | --- | --- |
| Hub / repeater | 1 | Nothing — repeats bits | Legacy; extend a segment |
| Switch | 2 | Destination MAC | Forward frames within a LAN / VLAN |
| Router | 3 | Destination IP | Forward packets between networks |
| NAT gateway | 3–4 | IP + port | Share a public IP; outbound internet for private hosts |
| Packet-filter / stateful firewall | 3–4 | 5-tuple + connection state | Allow / deny flows |
| L4 load balancer | 4 | IP + port (+ connection) | Spread TCP/UDP connections across backends |
| L7 load balancer / reverse proxy | 7 | HTTP host, path, headers, cookies | Route, terminate TLS, cache, compress |
| WAF / next-gen firewall | 7 | Request contents, signatures, identity | Block attacks in the payload |
| API gateway | 7 | Route + auth + quotas | Auth, rate limiting, transformation |

Real products often span layers: a "layer-3 switch" also routes, a cloud "application load balancer" is a reverse proxy, a next-gen firewall does both L4 filtering and L7 inspection. Name the **job** you need, then pick the box.

---

## 2) Components

### Hub (L1) → Switch (L2) → Router (L3)

- **Hub:** every bit out every port. One collision domain. Obsolete.
- **Switch:** learns MAC → port, forwards each frame only where needed. Each port its own collision domain; one broadcast domain per VLAN. Details in [`02-data-link-layer.md`](./02-data-link-layer.md).
- **Router:** connects different IP networks, uses longest-prefix match, decrements TTL, rewrites the L2 header every hop. It is the **broadcast-domain boundary**. Details in [`03-network-layer.md`](./03-network-layer.md).

### NAT gateway (L3/L4)

- Rewrites private source IP:port to a public IP:port and keeps a translation table.
- Gives private subnets **outbound** internet (updates, external APIs) without inbound exposure.
- Watch for port exhaustion and idle timeouts. **Not a firewall.**

### Firewalls

| Type | Layer | Sees | Example rule |
| --- | --- | --- | --- |
| Stateless packet filter / ACL | 3–4 | Each packet's IP, protocol, port | "Deny TCP to 10.0.3.0/24 port 5432 from 0.0.0.0/0" |
| Stateful firewall | 3–4 | Plus connection state | "Allow established/related; allow new TCP 443 from anywhere" |
| Host firewall | 3–4 | Same, on one machine | `nftables`, `ufw`, Windows Firewall |
| Cloud security group | 3–4 (stateful) | Attached to an instance/interface | "App SG may reach DB SG on 5432" |
| Cloud network ACL | 3–4 (stateless) | Subnet boundary | Both directions must be allowed |
| Kubernetes NetworkPolicy | 3–4 | Pod labels + ports | "Only `app=api` pods may reach `app=db`" |
| Next-gen firewall / WAF | 7 | URL, headers, body, user identity | "Block SQL injection patterns" |

Typical three-tier policy:

| From | To | Port | Action |
| --- | --- | --- | --- |
| Internet | Load balancer | 443 | Allow |
| Load balancer | App servers | 8080 | Allow |
| App servers | Database | 5432 | Allow |
| Internet | Database | any | **Deny** |
| anything else | anything | any | Deny (default) |

**Drop vs reject:** a *drop* makes the client wait for a **timeout**; a *reject* (TCP RST / ICMP unreachable) fails fast. Most internet-facing firewalls drop. When a connection times out while the service is healthy, check firewall rules and security groups before the code.

### Load balancer

Distributes requests or connections across a pool of **healthy** backends.

- **Scalability:** add backends as traffic grows; clients keep one address.
- **Availability:** **health checks** remove failed backends from rotation.

| | L4 load balancer | L7 load balancer |
| --- | --- | --- |
| Reads | IP, port, TCP/UDP | HTTP method, host, path, headers, cookies |
| Unit balanced | Connection / flow | Request |
| TLS | Passes through (or terminates) | Usually terminates |
| Routing | By port only | By host/path/header (`/api` → API pool) |
| Speed | Very fast, protocol-agnostic | More CPU, much more flexible |
| Examples | AWS NLB, IPVS, Maglev, HAProxy TCP mode | AWS ALB, NGINX, Envoy, HAProxy HTTP mode |

**Algorithms:** round robin, weighted round robin, least connections, least response time, consistent hashing (cache affinity), random-of-two.

**Health checks:** active (`GET /healthz` every N seconds) and passive (eject on errors). A health check should fail when the instance can't do real work, but not cascade (don't fail every instance because one shared dependency blipped).

**Other knobs:** connection draining on deploy, sticky sessions (avoid when possible — prefer shared state), cross-zone balancing, slow start for new instances.

### Reverse proxy

Sits **in front of servers** and acts on their behalf. Clients talk to the proxy; it talks to backends.

| Job | Why at the proxy |
| --- | --- |
| **TLS termination** | One place for certificates; offload crypto |
| **Routing** | `/api` → API service, `/static` → object storage, by host or path |
| **Caching** | Serve repeated responses without hitting the backend |
| **Compression** | gzip/Brotli once, centrally |
| **Hiding topology** | Internal hostnames, ports, and server count stay private |
| **Rate limiting, auth, headers** | Cross-cutting concerns out of every service |
| **Buffering** | Protect backends from slow clients |

**Forward vs reverse proxy:** a **forward** proxy acts for **clients** going out (corporate egress, content filtering). A **reverse** proxy acts for **servers** receiving traffic.

**Load balancer vs reverse proxy:** an L7 load balancer *is* a reverse proxy with a pool; a reverse proxy often load-balances. Their responsibilities overlap. A **CDN** is a globally distributed reverse proxy cache; an **API gateway** is a reverse proxy specialized for APIs.

### WAF and DDoS protection

- **WAF (L7):** inspects HTTP for injection, XSS, known exploit signatures, bots; OWASP Core Rule Set.
- **DDoS:** volumetric (L3/L4 floods, UDP amplification) absorbed by anycast/scrubbing; L7 floods handled with rate limits, challenges, caching.

---

## 3) End-to-end flow: request into a three-tier system

```
Client
  │  DNS → public IP of the load balancer
  ▼
[Edge: DDoS / WAF]           L3–L7   drop floods, block malicious requests
  ▼
[Firewall / SG: allow 443]   L3–L4
  ▼
[L7 LB / reverse proxy]      L7      terminate TLS, route /api → API pool, health-check
  ▼
[App server] (private subnet)
  │  outbound to a third-party API → [NAT gateway] → internet
  ▼
[Firewall / SG: app → db:5432 only]   L3–L4
  ▼
[Database] (data subnet, no internet route)
  ▲
Response retraces the path; the proxy may cache / compress it
```

Inside the LAN, every hop is still **switches (L2)** moving frames and **routers (L3)** moving packets between subnets.

---

## 4) Reliability, security, and ops

**Failure modes:**

| Symptom | Likely device |
| --- | --- |
| Timeout, healthy service | Firewall / security group dropping, missing route |
| Connection refused | Nothing listening, or a reject rule |
| 502 Bad Gateway | Proxy/LB reached no healthy backend, or backend reset |
| 503 Service Unavailable | All targets unhealthy, or overload protection |
| 504 Gateway Timeout | Backend too slow for the proxy's timeout |
| Works internally, fails externally | Edge firewall, LB listener, DNS pointing elsewhere |
| Random outbound failures | NAT gateway port exhaustion |
| Long-lived connections drop | LB / NAT / firewall idle timeout |

**Reliability controls:** redundant LBs across zones, health checks with sensible thresholds, connection draining, autoscaling behind the LB, multiple NAT gateways (one per zone), infrastructure as code for firewall rules with review.

**Security principles:**

- **Default deny**, allow only required flows (least privilege).
- **Defense in depth:** edge WAF + LB + security groups + host firewall + app auth.
- **Segment** with subnets and policies so a compromised web tier can't reach everything.
- **Encrypt** at the edge (TLS) and on internal hops you don't fully trust (mTLS / service mesh).
- **Log** firewall denies, LB access logs, and WAF blocks — dropped traffic is invisible otherwise.

**What to monitor:** LB healthy-host count, 5xx rate by target, request latency, active connections, firewall deny counts, NAT port allocation errors, WAF block rate, TLS cert expiry on listeners.

---

## 5) Hands-on commands and checks

| Command / check | What it shows |
| --- | --- |
| `sudo nft list ruleset` / `sudo iptables -L -n -v` | Host firewall rules and hit counters |
| `nc -vz host 5432` from inside vs outside the subnet | Which boundary blocks the flow |
| `curl -v https://lb-host/healthz` | LB → backend path and TLS |
| `curl -H 'Host: api.example.com' http://proxy/` | Host-based routing on a proxy |
| Cloud console: target group health | Which backends are in rotation, and why not |
| VPC flow logs | Accepted / rejected flows at L3–L4 |
| Proxy / LB access logs | Upstream chosen, status, latency per request |

---

## 6) Key takeaways

- A device's **layer** is the highest header it reads: switch = MAC (L2), router = IP (L3), L4 LB = ports, L7 proxy = HTTP.
- **Load balancers** spread work across healthy servers for scale and availability; L4 balances connections, L7 balances requests.
- **Reverse proxies** are the front door: TLS termination, routing, caching, compression, hiding internals. They overlap with L7 load balancers.
- **Firewalls** decide which flows are allowed; default deny, and keep databases unreachable from the internet.
- **NAT is not a firewall.** A timeout with a healthy app is often a **drop** at a boundary.

---

## 7) Quick glossary

- **Switch:** L2 device forwarding frames by MAC.
- **Router:** L3 device forwarding packets by IP.
- **NAT gateway:** Translates private to public addresses for outbound traffic.
- **Stateful firewall:** Tracks connections; allows return traffic automatically.
- **Security group:** Stateful cloud firewall attached to instances.
- **Network ACL:** Stateless subnet-level filter.
- **Load balancer:** Distributes traffic across a pool of healthy backends.
- **Health check:** Probe deciding whether a backend stays in rotation.
- **Reverse proxy:** Server-side intermediary in front of backends.
- **Forward proxy:** Client-side intermediary for outbound traffic.
- **WAF:** Web Application Firewall inspecting HTTP.
- **TLS termination:** Decrypting HTTPS at a proxy or LB.
- **Connection draining:** Letting in-flight work finish before removing a backend.

---

## 8) Sources & further reading

- RFC 9110 §3.7 — *Intermediaries (proxies, gateways)*: <https://www.rfc-editor.org/rfc/rfc9110#name-intermediaries>
- RFC 3022 — *Traditional IP NAT*: <https://www.rfc-editor.org/rfc/rfc3022>
- RFC 2979 — *Behavior of and Requirements for Internet Firewalls*: <https://www.rfc-editor.org/rfc/rfc2979>
- NIST SP 800-41 Rev. 1 — *Guidelines on Firewalls and Firewall Policy*: <https://csrc.nist.gov/pubs/sp/800/41/r1/final>
- AWS — *How Elastic Load Balancing works*: <https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/how-elastic-load-balancing-works.html>
- AWS — *Security groups vs network ACLs*: <https://docs.aws.amazon.com/vpc/latest/userguide/infrastructure-security.html>
- Google — *Maglev: A Fast and Reliable Software Network Load Balancer*: <https://research.google/pubs/maglev-a-fast-and-reliable-software-network-load-balancer/>
- NGINX — *Reverse proxy*: <https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/>
- Envoy — *What is Envoy*: <https://www.envoyproxy.io/docs/envoy/latest/intro/what_is_envoy>
- Kubernetes — *Network Policies*: <https://kubernetes.io/docs/concepts/services-networking/network-policies/>
- Cloudflare — *What is a reverse proxy?*: <https://www.cloudflare.com/learning/cdn/glossary/reverse-proxy/>
- OWASP — *Core Rule Set*: <https://coreruleset.org/>
