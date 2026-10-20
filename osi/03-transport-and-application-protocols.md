# Transport & Application Protocols — Detailed Notes

> Companion deep-dive for the summary diagram: `transport-application-protocols-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (chapters 10–13 and 17–18: TCP, the handshake, HTTPS/TLS, HTTP, WebSockets, UDP).

**Learning goal:** Choose and debug the protocol a RideNow feature actually needs — reliable ordered delivery for a ride request, TLS for account and location data, HTTP for the request/response, WebSockets for live driver position, and UDP where a newer sample beats a retransmit.

The packet can already reach the right machine ([notes 01](./01-addressing-dns-and-ports.md) and [02](./02-local-delivery-routing-nat.md)). This note is what the two endpoints do with it.

---

## 1) Big picture

| Concept | Problem it solves | RideNow example |
| --- | --- | --- |
| **TCP** | Reliable, ordered bytes between two sockets | The ride request must arrive complete |
| **Three-way handshake** | Both sides agree to a connection before data | Phone sets up the channel to the API |
| **UDP** | Datagrams without those guarantees, so less overhead | Real-time media, many DNS queries |
| **TLS** | Encryption, integrity, server authentication | Account, location, payment fields |
| **HTTP** | Request, then response | `POST /rides` and the result |
| **WebSockets** | A connection that stays open both ways | Push driver location; don't poll |

TCP is the right default when a missing or reordered byte would corrupt the action. UDP is the right choice when the newest update matters more than a perfect history. Neither replaces the other.

---

## 2) TCP and UDP

Both run at the transport layer and demultiplex with **ports**.

| | TCP | UDP |
| --- | --- | --- |
| Setup | Handshake, then a stream | None; each datagram stands alone |
| Delivery | Retransmits lost segments | No delivery guarantee |
| Order | Sequence numbers, in-order bytes | No ordering |
| Flow / congestion | Yes: windows, loss signals, backoff | No; the application paces itself |
| Header | 20 bytes, plus options | 8 bytes |
| RideNow fit | Ride request, account APIs, WebSocket transport | A live media leg, or a tiny status sample where stale-and-complete loses to fresh |

TCP also protects the network. **Flow control** stops the sender from overrunning the receiver's buffer. **Congestion control** slows down when the path is dropping packets, so one ride-share launch does not melt the links in between.

UDP leaves loss, order, and pacing to the application. That is a feature for voice, games, and some streaming: retransmitting a location sample that is already 500 ms old can be worse than waiting for the next one. DNS uses UDP for most queries because the message is small and a retry is cheap; it falls back to TCP when the answer is truncated or the exchange is a zone transfer.

---

## 3) TCP three-way handshake

No application bytes flow until both sides have exchanged initial sequence numbers:

```
Phone   ── SYN (seq = x) ──────────────▶  RideNow
Phone   ◀── SYN-ACK (seq = y, ack = x+1) ─ RideNow
Phone   ── ACK (ack = y+1) ─────────────▶  RideNow
        connection established; HTTP can start
```

- **SYN** — synchronize, here is my initial sequence number.
- **SYN-ACK** — I accept, here is mine, and I acknowledge yours.
- **ACK** — I acknowledge yours. The connection is open.

A graceful close is four steps, because each direction closes independently: `FIN → ACK`, then the other side's `FIN → ACK`.

The handshake costs a round trip before the first request byte. RideNow's app makes many calls during one session (quote, request, cancel, receipt), so it **reuses** the TCP connection (HTTP keep-alive, or a client pool) instead of shaking hands for every tap. A new handshake on every small request shows up as latency, not as a logic bug.

What failure looks like:

| Observation | Meaning |
| --- | --- |
| SYN sent, nothing back, then timeout | Filtered on the path, or the host is down. Firewalls often **drop** rather than refuse. |
| SYN, immediate RST | Something is reachable and actively refusing — wrong port, or nothing listening. |
| Handshake completes, then stall | The path works. Look at TLS or the application. |

---

## 4) HTTPS and TLS

The ride request carries account identity, pickup location, and sometimes payment data. **HTTPS** is HTTP inside **TLS**. TLS gives three properties:

1. **Confidentiality** — a passive observer on the path cannot read the bytes.
2. **Integrity** — modification is detected.
3. **Authentication** — the phone checks it is talking to RideNow, using a certificate, not merely to whoever answered the IP.

### TLS 1.3 handshake (simplified)

```
Phone ── ClientHello (cipher suites, key share) ──▶ RideNow
Phone ◀─ ServerHello (chosen suite, key share)
        Certificate, Finished                         ─ RideNow
Phone ── Finished ─────────────────────────────────▶ RideNow
        application data (the HTTP request) is encrypted from here
```

TLS 1.3 finishes in **one round trip** (1-RTT). Resumption can send early data in **0-RTT**; that data is not replay-safe, so it is a poor place for "request ride" or any non-idempotent call. Key agreement is **(EC)DHE**, which gives **forward secrecy**: a later leak of the server's long-term key does not decrypt today's capture.

### Certificates

1. The server presents an **X.509** certificate: public key plus the name `api.ridenow.example`.
2. A **certificate authority** signed it.
3. The phone trusts a set of root CAs shipped with the OS.
4. It walks the chain: leaf → intermediate → root, and checks name, dates, signature, and revocation (OCSP or CRL).

TLS does not have to terminate inside the ride service. A **reverse proxy** in front often terminates it, then may open a new encrypted hop to the internal service ([note 04](./04-infrastructure-and-network-security.md)). The passenger still sees HTTPS. The internal hop is a separate decision.

---

## 5) HTTP

With a secure connection up, **HTTP** carries the actual work. It is request, then response.

```
POST /v1/rides HTTP/1.1
Host: api.ridenow.example
Authorization: Bearer …
Content-Type: application/json

{"rider_id":"…","pickup":{…},"dropoff":{…}}
```

The backend validates the passenger, checks the ride, looks for a driver, and returns a status code plus a body (`201` with a trip id, or `422` if the dropoff is nonsense, or `503` if dispatch is down).

That request/response shape is what most RideNow APIs are. It is a poor fit for "tell me every time the driver moves," because the phone would have to ask on a timer even when nothing changed. That is the next section.

HTTP/2 and HTTP/3 change framing (binary streams; HTTP/3 rides on QUIC, which is UDP) without changing the request/response idea. The video's story still holds: HTTP asks, the server answers.

---

## 6) WebSockets

Once a driver accepts, the passenger watches the car move. Polling `GET /trips/{id}/location` every second creates traffic when the car is stopped at a light, and it adds a round trip to every update.

**WebSockets** (RFC 6455) start as an HTTP upgrade, then keep one connection open in both directions:

```
GET /v1/trips/8841/live HTTP/1.1
Upgrade: websocket
Connection: Upgrade
...
HTTP/1.1 101 Switching Protocols

...later, server pushes without a new request...
{"lat":12.9716,"lng":77.5946,"ts":"…"}
```

The server sends a frame whenever the driver location changes. The phone can send on the same socket (cancel, or a "I'm still here" ping). Underneath, this is still a **TCP** connection, so the bytes that do arrive are ordered and retransmitted. WebSockets do not become UDP by being "real-time."

Operational consequences:

- The connection is long-lived. Load balancers must not idle-timeout it below the ping interval.
- NAT mappings expire on quiet flows. Send **ping/pong** frames.
- Deploys must **drain** sockets, or every passenger's map drops at once.
- Sticky routing matters if location state for a trip lives on one process. Otherwise any server can push, and the shared bus (not the socket) is the source of truth.

---

## 7) When UDP is the better tool

WebSockets inherit TCP's reliability. Some RideNow-adjacent streams do not want that. A voice leg between driver and passenger, or a telemetry sample, gets worse if the stack pauses to retransmit packet n while packet n+5 is already on the wire.

Use UDP (or QUIC's UDP foundation, with its own loss rules) when:

- The application can tolerate or hide loss.
- A newer message **obsoletes** the missing one.
- The cost of a handshake dominates, as with a small DNS query.

Keep TCP when a partial ride request would be worse than a slow one. "UDP is faster" is incomplete. UDP has less machinery; the application takes on the machinery it still needs.

---

## 8) How the bytes are wrapped

On the way out, each layer adds a header. The ride request is nested:

```
[ Ethernet/Wi-Fi [ IP [ TCP [ TLS record [ HTTP POST /v1/rides ] ] ] ] ]
```

| Layer | Adds | RideNow contents |
| --- | --- | --- |
| HTTP | Method, path, headers, JSON body | Request ride |
| TLS | Record header, encryption, MAC | Hides that HTTP from the path |
| TCP | Ports, sequence, ack, flags | `51432 → 443`, ordered bytes |
| IP | Source and dest IP, TTL | Private source, later NAT-rewritten |
| Link | Source and dest MAC, checksum | Only for this hop; rewritten at each router |

The server unwraps in reverse: frame, packet, segment, TLS decrypt, HTTP handler. The response takes the same trip backward. NAT rewrites the destination of the reply back to the phone's private socket ([note 02](./02-local-delivery-routing-nat.md)).

---

## 9) End-to-end: request, then live map

```
1. TCP three-way handshake to api.ridenow.example:443
2. TLS 1.3 handshake; certificate name matches
3. HTTP POST /v1/rides  →  201 {trip_id}
4. HTTP Upgrade → WebSocket 101
5. Server pushes location frames as the driver moves
6. A separate voice or media leg, if any, can use UDP
   because a lost audio frame should not stall the next one
```

Risks: handshake filtered (timeout), certificate name mismatch, HTTP 401 from a bad token, WebSocket idle-killed by a proxy, UDP leg treated as "broken TCP" and retransmitted until the audio is late.

---

## 10) Reliability, security, and ops

- **Reuse TCP and TLS sessions.** Handshake cost dominates small API calls.
- **Do not send non-idempotent ride requests as TLS 0-RTT early data.** Replays would book twice.
- **Timeouts are not all the same.** SYN timeout → path or firewall. RST → nothing listening. HTTP 5xx → the service was reached.
- **WebSocket deploys need draining and heartbeats.** Measure connected sockets, not only request rate.
- **UDP features need their own sequence numbers and deadlines** in the application. The socket will not provide them.
- **Certificates:** automate issuance (ACME / Let's Encrypt or a private CA for internal hops), alert on expiry before the handshake starts failing.

---

## 11) Hands-on commands

| Command | What it shows |
| --- | --- |
| `curl -v https://api.ridenow.example/health` | DNS, TCP, TLS, and HTTP in one trace. |
| `openssl s_client -connect api.ridenow.example:443` | Certificate chain and negotiated TLS version. |
| `ss -tnp` | TCP state: `ESTAB`, `SYN-SENT`, `TIME-WAIT`. |
| `tcpdump -i any port 443` | Handshake flags on the wire (needs privileges). |

---

## 12) Key takeaways

- **TCP** gives a reliable ordered stream, with a **three-way handshake** before data and real cost if you reconnect every time.
- **TLS** adds encryption, integrity, and certificate authentication. Termination often happens at the proxy, not in the ride service.
- **HTTP** is the request/response that books the ride.
- **WebSockets** keep that channel open so the server can push driver location. They still run on TCP.
- **UDP** drops the delivery and ordering guarantees on purpose. Use it when fresh beats complete, not as a faster TCP.

---

## 13) Quick glossary

- **Segment:** TCP's unit (header + chunk of the byte stream).
- **Datagram:** UDP's unit. One send, one message, no stream.
- **SYN / ACK / FIN:** TCP flags for open, acknowledgement, and close.
- **TLS:** Transport Layer Security. HTTPS is HTTP over TLS.
- **Forward secrecy:** Past sessions stay secret if the long-term key leaks later.
- **WebSocket:** Persistent full-duplex channel, upgraded from HTTP.
- **QUIC:** UDP-based transport used by HTTP/3, with its own reliability rules.
- **Keep-alive:** Reusing one TCP connection for many HTTP requests.

---

## 14) Sources & further reading

**Transport**

- RFC 9293 — *Transmission Control Protocol (TCP)*: <https://www.rfc-editor.org/rfc/rfc9293>
- RFC 768 — *User Datagram Protocol*: <https://www.rfc-editor.org/rfc/rfc768>
- RFC 9000 — *QUIC*: <https://www.rfc-editor.org/rfc/rfc9000>

**HTTP, TLS, WebSockets**

- RFC 9110 — *HTTP semantics*: <https://www.rfc-editor.org/rfc/rfc9110>
- RFC 8446 — *TLS 1.3*: <https://www.rfc-editor.org/rfc/rfc8446>
- RFC 6455 — *The WebSocket Protocol*: <https://www.rfc-editor.org/rfc/rfc6455>
- MDN — *TLS*: <https://developer.mozilla.org/en-US/docs/Web/Security/Transport_Layer_Security>
- Cloudflare — *What happens in a TLS handshake?*: <https://www.cloudflare.com/learning/ssl/what-happens-in-a-tls-handshake/>
- Let's Encrypt — *How it works*: <https://letsencrypt.org/how-it-works/>

- Video (TCP, handshake, TLS, HTTP, WebSockets, UDP): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
