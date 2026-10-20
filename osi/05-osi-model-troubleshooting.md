# The OSI Model as a Troubleshooting Map — Detailed Notes

> Companion deep-dive for the summary diagram: `osi-troubleshooting-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (OSI chapter, about 21:29).

**Learning goal:** Use the seven OSI layers to isolate *where* a RideNow connection failed, after the individual mechanisms (IP, DNS, TCP, TLS, proxies) already make sense on their own.

This note is the map. The territory is the rest of the folder: [addressing](./01-addressing-dns-and-ports.md), [forwarding](./02-local-delivery-routing-nat.md), [protocols](./03-transport-and-application-protocols.md), [front door and firewalls](./04-infrastructure-and-network-security.md), and the [full request](./06-ridenow-request-journey.md).

---

## 1) Big picture

The **OSI model** (Open Systems Interconnection) splits networking into seven conceptual layers. It is a teaching and debugging model. The internet actually runs on the shorter **TCP/IP** stack. You do not need the seven names in order to pass an interview. You need them when RideNow "can't connect" and the error is only a timeout.

Each layer has one job, talks to the layer above and below, and on the way down adds a header (**encapsulation**). On the way up, that header comes off (**decapsulation**).

| Model | Layers | Use |
| --- | --- | --- |
| OSI | 7 | Isolate which kind of failure you have |
| TCP/IP | 4 (link, internet, transport, application) | What packets on the wire actually follow |

---

## 2) The seven layers, with RideNow attached

Top to bottom. The "RideNow" column is the concrete thing you already met, not a new protocol.

### Layer 7 — Application

- **Job:** The messages the program sends.
- **RideNow:** HTTP `POST /v1/rides`, DNS queries, WebSocket location frames.
- **Unit:** Data / message.
- **Fails when:** The connection is fine and the handler returns 401, 422, or 500. This *is* application code.

### Layer 6 — Presentation

- **Job:** Representation: encoding, compression, and encryption as the model teaches it.
- **RideNow:** TLS (confidentiality, integrity, certificates) and JSON encoding of the ride body.
- **Fails when:** Certificate name mismatch, expired cert, TLS version the peer refuses, or a body the other side cannot parse.
- **Honesty note:** On the real internet, TLS sits on top of TCP and is often implemented in the application or in the reverse proxy. OSI places "encryption" here so you remember to test it separately from "is the TCP port open?"

### Layer 5 — Session

- **Job:** Starting, keeping, and ending a conversation.
- **RideNow:** The long-lived WebSocket, HTTP keep-alive that reuses one TCP connection, a login session in a cookie or token.
- **Fails when:** A proxy idle-timeout kills the map socket, or a NAT mapping expires and the "session" is gone.
- **Honesty note:** TCP/IP has no separate session protocol for ordinary HTTPS. The useful question is still real: was a conversation established, and did it stay up?

### Layer 4 — Transport

- **Job:** End-to-end delivery between processes. **Ports live here.**
- **RideNow:** TCP for the ride request and the WebSocket; UDP for a media leg or a DNS query. The three-way handshake. Flow and congestion control.
- **Unit:** Segment (TCP) or datagram (UDP).
- **Fails when:** Nothing is listening on 443, the handshake times out, or a firewall drops the SYN.

### Layer 3 — Network

- **Job:** Logical addressing and routing across networks.
- **RideNow:** IPv4 or IPv6, the routing hop chain, NAT rewriting the phone's private source, subnet prefixes.
- **Unit:** Packet.
- **Fails when:** No route to the RideNow prefix, wrong gateway, TTL expiring, NAT port exhaustion.

### Layer 2 — Data link

- **Job:** Delivery between interfaces on the same link. **Frames and MAC addresses.**
- **RideNow:** Wi-Fi from the phone to the home router; Ethernet inside a cloud rack. ARP (IPv4) or NDP (IPv6) to learn the next-hop MAC.
- **Unit:** Frame.
- **Fails when:** ARP `FAILED`, wrong VLAN or subnet so the gateway is not actually on this link, Wi-Fi associated but not passing frames.

### Layer 1 — Physical

- **Job:** Signals on a medium.
- **RideNow:** Wi-Fi radio, fiber between zones, a cable, a NIC.
- **Unit:** Bits.
- **Fails when:** Radio down, interface `NO-CARRIER`, optics dead. No amount of HTTP retry helps.

---

## 3) How OSI maps onto the internet stack

| TCP/IP layer | OSI layers | You will see |
| --- | --- | --- |
| Application | 5, 6, 7 | HTTP, DNS, TLS, WebSocket messages |
| Transport | 4 | TCP, UDP, ports, handshake |
| Internet | 3 | IP, ICMP, routing, NAT |
| Link | 1, 2 | Ethernet, Wi-Fi, ARP, frames |

Anchors worth memorizing because they tell you which tool to open:

- **Ports → transport.**
- **Routing and IP → network.**
- **Frames and MAC → data link.**
- **TLS certificates → test them on their own**, even though the TCP connection underneath may already be up.

---

## 4) The debugging questions

RideNow cannot reach a dependency. Walk down or up, and stop at the first "no."

| Question | Layer | A "yes" looks like | A "no" looks like |
| --- | --- | --- | --- |
| Is the local link up? | 1–2 | Interface up, ARP/NDP resolves the gateway | No carrier, ARP failed |
| Can we reach the destination *network*? | 3 | `traceroute` gets to the far subnet; ping or TCP probes move | Hop dies in the middle; no route |
| Is the right service listening on the expected port? | 4 | `ss` shows `0.0.0.0:443` or the pod IP, not only `127.0.0.1` | Process up, socket bound to localhost |
| Can TCP complete a handshake? | 4 | SYN, SYN-ACK, ACK | Timeout (often a drop) or RST (refused) |
| Is TLS succeeding? | 6 | Certificate name matches, chain trusted, modern version | Expired cert, wrong hostname, protocol mismatch |
| Is the HTTP request reaching the backend? | 7 | Proxy log shows a status from the app | Proxy log empty → blocked before the app; 502 → app not answering |

The order is the point. A certificate error means layers 1–4 worked. A SYN timeout means you are not debugging JSON yet.

Two traps this ordering catches:

1. **The database is running and the password is correct**, and the client still times out. That is often layer 3 or 4: route, security group, or listen address. Application logs stay quiet because no request arrived.
2. **TCP connects and TLS fails.** The network path is fine. Rotate or fix the certificate; do not failover the region.

---

## 5) Encapsulation, one more time

```
HTTP ride request
  ↓ TLS record
TCP segment     source port, dest 443, sequence
  ↓
IP packet       source IP, dest IP, TTL
  ↓
Ethernet/Wi-Fi  source MAC, dest MAC, checksum
  ↓
bits on the medium
  ↓
each router: new link header, same IP destination (NAT may rewrite the source)
  ↓
server unwraps back up to the HTTP handler
```

A fuller protocol-level wrapping is in [note 03](./03-transport-and-application-protocols.md). The story of one passenger tap is in [note 06](./06-ridenow-request-journey.md).

---

## 6) Reliability, security, and ops

- **Put the layer in the alert.** "Handshake timeout to db:5432" pages the network rule owners. "HTTP 500 from trip service" pages the service owners. One undifferentiated "RideNow is down" wastes the model.
- **Capture at the narrowest layer that failed.** `traceroute` for a path, `openssl s_client` for TLS, proxy logs for HTTP. A full packet capture is the tool when those disagree.
- **Security controls sit at specific layers.** Firewalls are mostly layers 3–4 (and layer 7 if they understand HTTP). TLS is the confidentiality control. A subnet is a layer-3 boundary, not an authentication system.
- **Change one layer at a time.** Flipping DNS, the security group, and the app image in one incident leaves you unable to say which layer recovered.

---

## 7) Hands-on commands

| Command | Layer it informs |
| --- | --- |
| `ip link` / interface status | 1–2, is the NIC up? |
| `ip neigh` / `arp -a` | 2, does the gateway answer? |
| `ping` (ICMP) | 3, coarse reachability. Many firewalls block ICMP while TCP 443 works, so a failed ping is not proof. |
| `traceroute` / `tracepath` | 3, which hop stops. |
| `ss -lntp` | 4, who is listening, on which address. |
| `curl -v https://…` | 4 through 7 in one client trace. |
| `openssl s_client -connect host:443` | TLS, certificate, and negotiated version. |

---

## 8) Key takeaways

- OSI is a **debugging map**: which class of failure is this, not a stack you implement.
- The internet's working model is **TCP/IP**. Layers 5–7 collapse into "application" in practice, but you still test TLS separately from TCP and HTTP separately from TLS.
- Anchors: **ports at transport, routing at network, frames at data link.**
- A running process is not a working path. Walk link → route → port → handshake → TLS → HTTP.
- Encapsulation wraps headers on the way down and strips them on the way up, at every hop.

---

## 9) Quick glossary

- **OSI:** Seven-layer reference model from ISO/IEC 7498-1.
- **TCP/IP stack:** The four-layer model the internet uses.
- **Encapsulation:** Adding a layer's header around the payload from above.
- **Decapsulation:** Removing that header on receive.
- **PDU:** Protocol data unit — the blob a layer thinks it sends (segment, packet, frame, bit).
- **Middlebox:** A NAT, firewall, or proxy that is not an endpoint. It rewrites or drops along the path.

---

## 10) Sources & further reading

- ISO/IEC 7498-1 — *OSI Basic Reference Model*: <https://www.iso.org/standard/20269.html>
- RFC 1122 — *Requirements for Internet Hosts — Communication Layers*: <https://www.rfc-editor.org/rfc/rfc1122>
- RFC 1123 — *Requirements for Internet Hosts — Application and Support*: <https://www.rfc-editor.org/rfc/rfc1123>
- Cloudflare — *What is the OSI model?*: <https://www.cloudflare.com/learning/ddos/glossary/open-systems-interconnection-model-osi/>
- MDN — *How does the internet work?*: <https://developer.mozilla.org/en-US/docs/Learn_web_development/Howto/Web_mechanics/How_does_the_Internet_work>
- IBM — *The OSI model*: <https://www.ibm.com/think/topics/osi-model>
- Video, OSI chapter: <https://www.youtube.com/watch?v=TR0RU2pmMeA&t=1289s>
