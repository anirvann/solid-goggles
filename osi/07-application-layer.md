# Layer 7 — Application — Detailed Notes

> Companion deep-dive for the summary diagram: `application-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand the protocols applications speak directly — DNS to find hosts, DHCP to configure them, HTTP for request/response, WebSockets for persistent two-way updates — and how to choose between them.

---

## 1) Big picture

Layer 7 is where **network-aware applications** talk. It is not the app's UI; it is the protocol the app uses: "get this page," "resolve this name," "send this email," "push this update."

Responsibilities:

- Defining **messages and their meaning** (methods, status codes, record types).
- **Naming** resources (URLs, hostnames).
- Application-level **auth, caching, and error semantics**.

**PDU:** message / data.

| Protocol | Transport | Port | Purpose |
| --- | --- | --- | --- |
| DNS | UDP (TCP for large / zone transfer), also DoT/DoH | 53 (853, 443) | Name → address |
| DHCP | UDP | 67 / 68 | Automatic IP configuration |
| HTTP/1.1, HTTP/2 | TCP (+TLS) | 80 / 443 | Request / response |
| HTTP/3 | QUIC (UDP) | 443 | Request / response, no TCP HOL blocking |
| WebSocket | TCP (+TLS) | 80 / 443 | Persistent two-way messages |
| SSH | TCP | 22 | Remote shell, tunnels |
| SMTP / IMAP | TCP | 25, 587 / 993 | Email |
| NTP | UDP | 123 | Time sync |
| gRPC | HTTP/2 | 443 | RPC with Protobuf |

---

## 2) Components

### DNS (Domain Name System)

Translates a **hostname** into IP addresses (and more). Users and programs use names; the network needs addresses.

**Resolution path:**

```
App → stub resolver (OS) → cache hit? done
                         → recursive resolver (ISP, 1.1.1.1, 8.8.8.8, VPC resolver)
                              → root servers   → "ask .com"
                              → .com TLD       → "ask example.com's nameservers"
                              → authoritative  → A 198.51.100.10  TTL 300
                         ← answer cached at every level for TTL seconds
```

**Common record types:**

| Record | Holds |
| --- | --- |
| A / AAAA | IPv4 / IPv6 address |
| CNAME | Alias to another name |
| MX | Mail servers |
| TXT | Arbitrary text (SPF, domain verification) |
| NS | Authoritative nameservers for a zone |
| SOA | Zone metadata |
| SRV | Service host + port |
| CAA | Which CAs may issue certs |

**Caching and TTL:** every answer carries a **TTL**. Caches (browser, OS, resolver) reuse it until it expires. Long TTL = fewer lookups but **slow changes and failovers**. Lower TTLs *before* a migration.

**One name, many addresses:** multiple A/AAAA records spread clients (simple load distribution); GeoDNS answers differently by location.

**Security:** DNSSEC (signed answers), DoT/DoH (encrypted queries), watch for cache poisoning and dangling CNAMEs (subdomain takeover).

### DHCP (Dynamic Host Configuration Protocol)

Hands a device its network configuration automatically when it joins a network.

**DORA exchange (IPv4, over UDP broadcast):**

```
Client  Discover  (broadcast)  "I need an address"
Server  Offer                  "You can have 192.168.1.42"
Client  Request                "I'll take 192.168.1.42"
Server  Ack                    "It's yours for 24 h" + options
```

Provides: IP address, subnet mask, **default gateway**, **DNS servers**, lease time (plus optional NTP, domain, etc.). Leases are renewed at ~50 % of their lifetime.

Relays (`ip helper`) forward DHCP across subnets. IPv6 hosts often use **SLAAC** instead, or DHCPv6.

Risks: pool exhaustion, a **rogue DHCP server** handing out a malicious gateway/DNS (mitigation: DHCP snooping).

### HTTP (Hypertext Transfer Protocol)

**Request / response**, stateless by design.

```
GET /api/items/42 HTTP/1.1
Host: example.com
Accept: application/json
Authorization: Bearer …

HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: max-age=60

{"id": 42, "name": "…"}
```

**Methods:**

| Method | Meaning | Safe | Idempotent |
| --- | --- | --- | --- |
| GET | Read | Yes | Yes |
| HEAD | Headers only | Yes | Yes |
| POST | Create / process | No | No |
| PUT | Replace | No | Yes |
| PATCH | Partial update | No | No (usually) |
| DELETE | Remove | No | Yes |
| OPTIONS | Capabilities / CORS preflight | Yes | Yes |

**Status codes:** `1xx` informational (101 Switching Protocols), `2xx` success (200, 201, 204), `3xx` redirect (301, 302, 304 Not Modified), `4xx` client error (400, 401, 403, 404, 409, 429), `5xx` server error (500, 502 Bad Gateway, 503, 504 Gateway Timeout).

**Important headers:** `Host`, `Content-Type`, `Authorization`, `Cookie`/`Set-Cookie`, `Cache-Control`, `ETag`/`If-None-Match`, `Accept-Encoding`, `Location`.

**Versions:**

| Version | Transport | Key change |
| --- | --- | --- |
| HTTP/1.1 | TCP | Text, keep-alive, one request at a time per connection |
| HTTP/2 | TCP | Binary frames, many streams on one connection, header compression |
| HTTP/3 | QUIC/UDP | Streams without TCP head-of-line blocking, faster setup |

Semantics (methods, status codes, headers) stay the same across versions.

### WebSockets

HTTP is client-initiated: the server can only answer. For live updates (chat, dashboards, live location, notifications), **polling** wastes requests and adds latency.

**WebSocket** upgrades an HTTP connection to a persistent, **full-duplex** message channel:

```
GET /live HTTP/1.1
Host: example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: …
Sec-WebSocket-Version: 13

HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: …

… now either side sends frames at any time (text, binary, ping, pong, close)
```

- Runs over **TCP** (so messages that arrive are reliable and ordered) and usually TLS (`wss://`).
- Long-lived → needs heartbeats, LB/proxy upgrade support, idle-timeout tuning, connection draining on deploy, and a fan-out layer (pub/sub) when many servers hold connections.

**Choosing a real-time pattern:**

| Pattern | Direction | Best for |
| --- | --- | --- |
| Short polling | Client asks repeatedly | Rare updates, simplest |
| Long polling | Client asks, server holds until data | Fallback for old infra |
| Server-Sent Events (SSE) | Server → client over HTTP | One-way feeds, notifications |
| WebSocket | Both ways | Chat, collaboration, live tracking |
| WebRTC / UDP | Peer-to-peer, media | Voice/video, low latency |

---

## 3) End-to-end flow: loading `https://example.com/app`

```
0. DHCP (earlier): laptop got IP, gateway, DNS server
1. DNS: example.com → A 198.51.100.10 (cached for TTL)
2. TCP handshake to :443 (layer 4)
3. TLS handshake, ALPN picks h2 (layer 6)
4. HTTP/2 GET /app → 200 OK, HTML
5. More GETs for CSS/JS/images on the same connection
6. JS opens wss://example.com/live → 101 Switching Protocols
7. Server pushes updates as WebSocket messages
```

---

## 4) Reliability, security, and ops

**Failure modes:**

- **DNS:** stale cache after a change (TTL), NXDOMAIN from a typo or expired domain, slow resolver adding latency to every new host.
- **DHCP:** exhausted pool → new devices get `169.254.x.x` (link-local) and no internet.
- **HTTP:** 502/504 from a proxy (backend down or slow), 429 rate limiting, 503 overload, retries on non-idempotent POST causing duplicates (use idempotency keys).
- **WebSockets:** dropped by LB idle timeouts, mass reconnect storms after deploys.

**Reliability controls:** timeouts on every call, retries with exponential backoff and jitter (only for idempotent operations or with idempotency keys), circuit breakers, caching (`Cache-Control`, ETags, CDNs), health checks, graceful degradation.

**Security:**

- Authentication / authorization on every request (OAuth 2.0, tokens, mTLS for services).
- Input validation; OWASP Top 10 (injection, broken access control, SSRF…).
- **WAF** and rate limiting at the edge (see [`08-devices-and-security-across-layers.md`](./08-devices-and-security-across-layers.md)).
- CORS configured narrowly; secure cookies; security headers (CSP, HSTS).
- DNS: DNSSEC, registrar lock, monitor for dangling records.

**What to monitor:** request rate, error rate, latency percentiles (RED metrics), status-code distribution, DNS resolution time and failures, DHCP pool usage, active WebSocket connections and reconnect rate.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `dig example.com A +short` | Resolved IPv4 addresses |
| `dig example.com AAAA` | IPv6 addresses and TTL |
| `dig +trace example.com` | Root → TLD → authoritative walk |
| `resolvectl status` / `cat /etc/resolv.conf` | Which DNS server the host uses |
| `sudo dhclient -v eth0` / `ipconfig /renew` | DHCP exchange |
| `curl -v https://example.com` | Full HTTP request/response with headers |
| `curl -sI https://example.com` | Response headers only |
| `curl --http3 https://example.com` | Try HTTP/3 (if built with support) |
| `websocat wss://echo.websocket.org` | Interactive WebSocket client |

---

## 6) Key takeaways

- **DNS** turns names into addresses; **TTL** controls how long answers are cached.
- **DHCP** gives devices their IP, gateway, and DNS automatically.
- **HTTP** is request/response; methods and status codes carry meaning; idempotency matters for retries.
- **WebSockets** keep one connection open both ways so the server can **push**; they still run on TCP.
- Choose the protocol by the **interaction pattern**, not by popularity.

---

## 7) Quick glossary

- **Hostname / FQDN:** Human-readable name (`www.example.com.`).
- **Resolver:** Server that performs DNS lookups on a client's behalf.
- **Authoritative server:** Holds the real records for a zone.
- **TTL:** Cache lifetime of a DNS answer.
- **Lease:** Time a DHCP-assigned address is valid.
- **Idempotent:** Repeating the request has the same effect as doing it once.
- **Status code:** Three-digit HTTP result (2xx success, 4xx client error, 5xx server error).
- **Upgrade / 101:** HTTP mechanism used to switch to WebSocket.
- **SSE:** Server-Sent Events, one-way server push over HTTP.

---

## 8) Sources & further reading

- RFC 1034 / RFC 1035 — *Domain Names*: <https://www.rfc-editor.org/rfc/rfc1034>, <https://www.rfc-editor.org/rfc/rfc1035>
- RFC 8484 — *DNS over HTTPS*: <https://www.rfc-editor.org/rfc/rfc8484>
- RFC 2131 — *DHCP*: <https://www.rfc-editor.org/rfc/rfc2131>
- RFC 9110 — *HTTP Semantics*: <https://www.rfc-editor.org/rfc/rfc9110>
- RFC 9113 — *HTTP/2*: <https://www.rfc-editor.org/rfc/rfc9113>
- RFC 9114 — *HTTP/3*: <https://www.rfc-editor.org/rfc/rfc9114>
- RFC 6455 — *The WebSocket Protocol*: <https://www.rfc-editor.org/rfc/rfc6455>
- MDN — *HTTP overview*: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview>
- MDN — *WebSockets API*: <https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API>
- Cloudflare — *What is DNS?*: <https://www.cloudflare.com/learning/dns/what-is-dns/>
- OWASP Top 10: <https://owasp.org/www-project-top-ten/>
