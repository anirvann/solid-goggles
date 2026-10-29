# Layer 4 — Transport — Detailed Notes

> Companion deep-dive for the summary diagram: `transport-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand how ports deliver data to the right process, how TCP provides reliable ordered delivery (including the three-way handshake), when UDP's lighter model is the better choice, and where QUIC fits.

---

## 1) Big picture

Layer 3 gets a packet to the right **host**. Layer 4 gets the data to the right **process** on that host and decides **how much reliability** the conversation gets.

Responsibilities:

- **Multiplexing** with **ports**.
- **Segmentation and reassembly** of application data.
- Optionally: **reliability, ordering, flow control, congestion control** (TCP, QUIC).

**PDU:** segment (TCP) or datagram (UDP).

---

## 2) Components

### Ports and sockets

- A **port** is a 16-bit number (0–65535) that identifies a service on a host. The IP is the building; the port is the apartment.
- A connection is identified by the **5-tuple**: protocol, source IP, source port, destination IP, destination port.

| Range | Name | Use |
| --- | --- | --- |
| 0–1023 | Well-known | Standard services (need privileges to bind on Unix) |
| 1024–49151 | Registered | Applications (3306 MySQL, 5432 PostgreSQL, 6379 Redis, 8080 alt HTTP) |
| 49152–65535 | Dynamic / ephemeral | Client source ports |

| Port | Service |
| --- | --- |
| 22 | SSH |
| 25 | SMTP |
| 53 | DNS (UDP and TCP) |
| 67/68 | DHCP (UDP) |
| 80 | HTTP |
| 123 | NTP (UDP) |
| 443 | HTTPS (TCP), HTTP/3 (UDP) |

**Bind address matters.** A server listening on `127.0.0.1:8080` is only reachable from the same machine. `0.0.0.0:8080` (or `[::]:8080`) accepts on all interfaces. "The app is running but nobody can connect" is very often this.

### TCP (Transmission Control Protocol)

Connection-oriented, reliable, ordered **byte stream**.

| Mechanism | What it does |
| --- | --- |
| **Sequence numbers** | Every byte is numbered so the receiver can reorder and detect gaps |
| **Acknowledgements** | Receiver confirms what it got; cumulative ACK + SACK |
| **Retransmission** | Missing data is resent after a timeout or duplicate ACKs |
| **Flow control** | Receive **window** stops a sender from overrunning the receiver |
| **Congestion control** | Slow start, congestion avoidance (Reno, CUBIC, BBR) to avoid overloading the network |
| **Checksum** | Detects corrupted segments |

Header: 20 bytes minimum (ports, seq, ack, flags, window, checksum, options).

### TCP three-way handshake

```
Client ── SYN (seq=x) ───────────────▶ Server     "I want to talk; my ISN is x"
Client ◀── SYN-ACK (seq=y, ack=x+1) ── Server     "OK; my ISN is y; got yours"
Client ── ACK (ack=y+1) ─────────────▶ Server     "Got yours"
            connection ESTABLISHED
```

- It costs **one round trip** before any data, which is why clients **reuse connections** (HTTP keep-alive, connection pools).
- **Close** is a four-way exchange (`FIN`, `ACK`, `FIN`, `ACK`) because each direction closes independently. The side that closes first sits in **TIME_WAIT** for a while.
- **RST** aborts a connection immediately ("nothing listening here," or a hard error).

Connection states you'll see: `LISTEN`, `SYN-SENT`, `SYN-RECEIVED`, `ESTABLISHED`, `FIN-WAIT`, `CLOSE-WAIT`, `TIME-WAIT`.

### UDP (User Datagram Protocol)

Connectionless, **message-oriented**, minimal.

- 8-byte header: source port, destination port, length, checksum.
- No handshake, no retransmission, no ordering, no congestion control.
- Each `send` is one datagram; it arrives whole, or not at all.

UDP is not "TCP but faster." It is less machinery — the application takes on whatever reliability it needs.

### TCP vs UDP

| | TCP | UDP |
| --- | --- | --- |
| Connection | Handshake first | None |
| Delivery | Guaranteed (retransmit) | Best effort |
| Order | In order | Any order |
| Flow / congestion control | Yes | No (app's job) |
| Unit | Byte stream | Discrete datagrams |
| Header | 20+ B | 8 B |
| Head-of-line blocking | Yes — one lost segment stalls later data | No |
| Typical use | Web, APIs, SSH, email, DB connections, file transfer | DNS queries, VoIP, video calls, games, streaming telemetry, DHCP, NTP |

**Choose TCP** when every byte must arrive in order (a payment, an API call, a file).
**Choose UDP** when fresh beats complete — a late voice packet or game state update is worse than a missing one — or when the exchange is one tiny request/response (DNS).

### QUIC

- A modern transport built **on top of UDP** (RFC 9000), used by **HTTP/3**.
- Provides reliability, ordering **per stream** (no head-of-line blocking across streams), congestion control, and **built-in TLS 1.3**.
- Combines transport and crypto handshakes: 1-RTT new connections, 0-RTT resumption.
- Connection IDs survive IP changes (Wi-Fi → cellular).

---

## 3) End-to-end flow: data reaching a process

```
Client app: connect(198.51.100.10, 443)
1. OS picks ephemeral source port 51432
2. TCP handshake: SYN → SYN-ACK → ACK
3. App writes bytes; TCP splits them into segments (≤ MSS)
4. Each segment: [src 51432 | dst 443 | seq | ack | window] + data
5. Server TCP ACKs, reorders, asks for retransmits of gaps
6. Server OS delivers the byte stream to the socket bound to :443
7. Close: FIN/ACK in each direction; client sits in TIME_WAIT
```

---

## 4) Reliability, security, and ops

**Failure signatures:**

| Observation | Likely meaning |
| --- | --- |
| SYN sent, no reply, timeout | Packet **dropped** — firewall, security group, routing, host down |
| SYN → immediate RST | Host reachable, **nothing listening** on that port |
| Handshake OK, then hang | Path fine; look higher (TLS, app) or at MTU |
| Many retransmissions | Packet loss or congestion on the path |
| Lots of `TIME_WAIT` | Many short connections — reuse them |
| Lots of `CLOSE_WAIT` | Your app isn't closing sockets (a bug) |
| "Too many open files" / port exhaustion | Too many connections; pool and reuse |

**Reliability controls:** connection pooling and keep-alive, sensible connect/read timeouts, retries with backoff and jitter, TCP keepalives (or app heartbeats) to survive NAT/LB idle timeouts, graceful connection draining.

**Security:**

- **SYN flood** — exhaust half-open connections. Mitigation: SYN cookies, upstream DDoS protection.
- **UDP amplification** — small spoofed requests (DNS, NTP, memcached) yield big replies at a victim. Mitigation: rate limits, don't expose open UDP services.
- **Port scanning** — expose only needed ports; default-deny firewalls.
- Stateful firewalls track TCP state and allow return traffic automatically.

**What to monitor:** connection counts by state, retransmit rate, RTT, SYN backlog drops, ephemeral port usage, listen queue overflows.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ss -lntp` / `ss -lunp` | Listening TCP / UDP sockets, bind address, process |
| `ss -tan state established` | Active TCP connections |
| `ss -ti` | Per-connection RTT, cwnd, retransmits |
| `nc -vz host 443` | Can a TCP handshake complete? |
| `nc -vu host 53` | Send a UDP probe |
| `tcpdump -i any 'tcp[tcpflags] & (tcp-syn) != 0'` | Watch SYNs / SYN-ACKs |
| `netstat -s` | Protocol counters (retransmits, resets) |

---

## 6) Key takeaways

- **Ports** pick the process; the **5-tuple** identifies a connection.
- **TCP**: reliable, ordered, flow- and congestion-controlled, with a **three-way handshake** that costs one RTT — reuse connections.
- **UDP**: no guarantees, low overhead; use it when **fresh beats complete** or the exchange is tiny.
- Neither is "better" — choose by requirement. **QUIC** brings TCP-like reliability on UDP with built-in TLS.
- **Timeout = dropped, RST = refused.** That one distinction saves hours of debugging.

---

## 7) Quick glossary

- **Port:** 16-bit service identifier on a host.
- **Ephemeral port:** Short-lived client source port.
- **Socket:** Endpoint = IP + port + protocol.
- **5-tuple:** Protocol + source/destination IP + source/destination port.
- **SYN / ACK / FIN / RST:** TCP flags for open, acknowledge, close, abort.
- **ISN:** Initial sequence number.
- **MSS:** Maximum segment size (payload per TCP segment).
- **Window:** How much unacknowledged data a sender may have in flight.
- **Head-of-line blocking:** One lost packet delaying everything behind it.
- **QUIC:** UDP-based, encrypted, multiplexed transport used by HTTP/3.

---

## 8) Sources & further reading

- RFC 9293 — *Transmission Control Protocol (TCP)*: <https://www.rfc-editor.org/rfc/rfc9293>
- RFC 768 — *User Datagram Protocol*: <https://www.rfc-editor.org/rfc/rfc768>
- RFC 5681 — *TCP Congestion Control*: <https://www.rfc-editor.org/rfc/rfc5681>
- RFC 9000 — *QUIC*: <https://www.rfc-editor.org/rfc/rfc9000>
- RFC 4987 — *TCP SYN Flooding Attacks and Common Mitigations*: <https://www.rfc-editor.org/rfc/rfc4987>
- IANA — *Service name and port number registry*: <https://www.iana.org/assignments/service-names-port-numbers/>
- Cloudflare — *What is UDP?*: <https://www.cloudflare.com/learning/ddos/glossary/user-datagram-protocol-udp/>
- Cloudflare — *What is a TCP three-way handshake?* (SYN flood context): <https://www.cloudflare.com/learning/ddos/syn-flood-ddos-attack/>
