# OSI & Networking Visual Notes

Sketchbook-style visual learning notes for networking fundamentals.

Each topic has **two parts**:
- a **summary diagram** (`.png`) — the quick, visual sketchbook overview, and
- a **detailed markdown** (`.md`) — the in-depth reference with source links.

| Topic | Summary diagram | Detailed notes |
| --- | --- | --- |
| OSI + practical layers | `networking-layers-sketchbook.png` | [`01-osi-and-networking-layers.md`](./01-osi-and-networking-layers.md) |
| Transport, IP & secure web | `tcp-udp-tls-packet-journey.png` | [`02-transport-ip-secure-web.md`](./02-transport-ip-secure-web.md) |

## Diagrams

### 1. Networking Layers (OSI + Practical View)

![Networking Layers](./networking-layers-sketchbook.png)

Detailed notes: [`01-osi-and-networking-layers.md`](./01-osi-and-networking-layers.md)

Covers:
- The 7 OSI layers (Application → Physical) with concise bullets per layer
- Practical internet stack mapping (Application, Transport, Internet, Link)
- Where ports, routing, and frames live
- High-level packet journey: Browser → TCP → IP → Ethernet → Wire → Router → Server
- Handy commands: `ping`, `traceroute`, `netstat`

### 2. Transport, IP & Secure Web: Deep Dive

![TCP/UDP, IP, TLS and Packet Journey](./tcp-udp-tls-packet-journey.png)

Detailed notes: [`02-transport-ip-secure-web.md`](./02-transport-ip-secure-web.md)

Covers:
- **TCP vs UDP**: reliability, ordering, use cases
- **TCP 3-way handshake**: SYN → SYN-ACK → ACK, plus teardown
- **IPv4 vs IPv6**: address size, format, NAT differences
- **HTTPS / TLS handshake**: ClientHello → ServerHello → Certificate → key exchange → encrypted data
- **Certificates & trust**: CA signing, chain verification, public/private keys
- **Detailed packet journey**: header encapsulation across layers (HTTP → TLS → TCP → IP → Ethernet → wire → router/NAT → server) and decapsulation
- Handy commands: `dig`, `curl -v`, `openssl s_client`, `tcpdump`

## Style

Both diagrams follow the repository's sketchbook visual style. See:
- `docs/sketchbook-style-guide.md`
- `docs/system-design-note-template.md`
