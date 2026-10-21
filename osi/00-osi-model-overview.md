# The OSI Model: How the Layers Fit Together — Summary Notes

> Companion deep-dive for the summary diagram: `osi-overview-sketchbook.png`.
> The image is the quick summary; this document is the reference that ties the per-layer notes together.

**Learning goal:** See the seven OSI layers as one system — what each layer hands to the next, how a request is wrapped on the way down and unwrapped on the way up, and how to use the layers to locate a failure.

Per-layer deep dives:

| Layer | Name | Notes | Diagram |
| --- | --- | --- | --- |
| 7 | Application | [`07-application-layer.md`](./07-application-layer.md) | `application-layer-sketchbook.png` |
| 6 | Presentation | [`06-presentation-layer.md`](./06-presentation-layer.md) | `presentation-layer-sketchbook.png` |
| 5 | Session | [`05-session-layer.md`](./05-session-layer.md) | `session-layer-sketchbook.png` |
| 4 | Transport | [`04-transport-layer.md`](./04-transport-layer.md) | `transport-layer-sketchbook.png` |
| 3 | Network | [`03-network-layer.md`](./03-network-layer.md) | `network-layer-sketchbook.png` |
| 2 | Data link | [`02-data-link-layer.md`](./02-data-link-layer.md) | `data-link-layer-sketchbook.png` |
| 1 | Physical | [`01-physical-layer.md`](./01-physical-layer.md) | `physical-layer-sketchbook.png` |
| 1–7 | Devices and security across layers | [`08-devices-and-security-across-layers.md`](./08-devices-and-security-across-layers.md) | `devices-across-layers-sketchbook.png` |

---

## 1) Big picture

The **OSI model** (Open Systems Interconnection, ISO/IEC 7498-1) splits communication into seven layers. Each layer:

- has one job,
- uses the service of the layer directly below it,
- offers a service to the layer directly above it, and
- talks *logically* to the same layer on the other machine, by adding its own header.

The internet does not implement OSI literally. It runs the **TCP/IP** stack, which has four layers. OSI is still the shared vocabulary: "that's a layer-4 load balancer," "this is a layer-2 problem," "the firewall works at layer 7."

| OSI layer | Job in one line | PDU | Address / identifier | Examples |
| --- | --- | --- | --- | --- |
| 7 Application | What the program is asking for | Message | URL, hostname | HTTP, DNS, DHCP, WebSocket, SMTP, SSH |
| 6 Presentation | How the bytes are represented and protected | — | — | TLS, UTF-8, JSON, gzip, JPEG |
| 5 Session | Start, keep, resume, and end a conversation | — | Session ID, token | TLS sessions, RPC sessions, keep-alive |
| 4 Transport | Process-to-process delivery | Segment / datagram | Port | TCP, UDP, QUIC |
| 3 Network | Host-to-host across networks | Packet | IP address | IPv4, IPv6, ICMP, routing |
| 2 Data link | Node-to-node on one link | Frame | MAC address | Ethernet, Wi-Fi, ARP, VLANs |
| 1 Physical | Bits as signals on a medium | Bit | — | Copper, fiber, radio, NIC, cable |

---

## 2) How OSI maps onto TCP/IP

| TCP/IP layer | OSI layers | What actually runs |
| --- | --- | --- |
| Application | 7, 6, 5 | HTTP, DNS, TLS, WebSocket — usually in one library or process |
| Transport | 4 | TCP, UDP, QUIC |
| Internet | 3 | IP, ICMP |
| Link | 2, 1 | Ethernet, Wi-Fi, the NIC driver and hardware |

Layers 5 and 6 rarely exist as separate protocols in TCP/IP. Their *functions* still exist — TLS encrypts (6), HTTP keep-alive and TLS resumption manage sessions (5) — but they live inside the application or a library. That is why the per-layer notes for 5 and 6 point at concrete TCP/IP mechanisms instead of a dedicated protocol.

Anchors worth memorizing:

- **Ports → layer 4.**
- **IP addresses and routing → layer 3.**
- **MAC addresses, frames, and switches → layer 2.**
- **Encryption (TLS) → layer 6 in OSI terms**, even though it runs on top of TCP in practice.

---

## 3) Encapsulation: how the layers fit together

On the sender, each layer takes the payload from above and adds its own header (and the link layer adds a trailer). On the receiver, each layer strips its header and hands the payload up. Every layer only reads *its own* header.

```
L7  HTTP request:     GET /index.html  Host: example.com
L6  TLS record:       [TLS hdr | encrypted HTTP ............ | MAC/tag]
L5  session state:    reuses an existing TLS session / connection
L4  TCP segment:      [src port | dst port 443 | seq | ack | flags | TLS record]
L3  IP packet:        [src IP | dst IP | TTL | proto=TCP | TCP segment]
L2  Ethernet frame:   [dst MAC | src MAC | type=IPv4 | IP packet | FCS]
L1  bits:             01011010 11001010 ... as voltage, light, or radio
```

Nested view:

```
[ Ethernet [ IP [ TCP [ TLS [ HTTP ] ] ] ] FCS ]
```

What changes along the path:

| Header | Changes at each hop? | Who rewrites it |
| --- | --- | --- |
| L2 MAC addresses | **Yes**, every hop | Each router builds a new frame for the next link |
| L3 IP addresses | No (end to end) | Except **NAT**, which rewrites source or destination |
| L3 TTL / hop limit | Yes, decremented | Each router |
| L4 ports | No | Except **NAPT**, which rewrites the source port |
| L6/L7 contents | No | Except a proxy that terminates TLS and opens a new connection |

---

## 4) End-to-end flow: a browser loads `https://example.com`

```
 1. L7  DHCP already gave the laptop an IP, gateway, and DNS server
 2. L7  DNS resolves example.com → 198.51.100.10   (over UDP 53, or TCP / DoH)
 3. L3  Destination not in the local subnet → send to the default gateway
 4. L2  ARP: "who has 192.168.1.1?" → gateway's MAC
 5. L1  Frame becomes radio or electrical signals
 6. L3  Home router: NAT rewrites the private source to a public IP:port
 7. L3  Routers forward hop by hop; a new L2 frame on every link
 8. L4  TCP three-way handshake with port 443
 9. L6  TLS handshake; certificate checked; keys agreed
10. L5  Session established; later requests reuse it
11. L7  HTTP GET; server responds 200
12.     Server decapsulates L1 → L7; the response makes the same trip back
```

Every step has its own failure mode, which is the whole point of the next section.

---

## 5) Using the layers to troubleshoot

Walk from the bottom up (or top down) and stop at the first "no":

| Question | Layer | Tool | A "no" usually means |
| --- | --- | --- | --- |
| Is the link up? | 1 | `ip link`, LEDs, Wi-Fi status | Cable, radio, NIC, optics |
| Can I reach the next hop on this link? | 2 | `ip neigh`, `arp -a` | ARP failing, wrong VLAN |
| Can I reach the destination network? | 3 | `ping`, `traceroute`, `ip route get` | No route, NAT, ICMP filtered |
| Is something listening on the port? | 4 | `ss -lntp`, `nc -vz host 443` | Service down or bound to localhost |
| Does the TCP handshake finish? | 4 | `curl -v`, `tcpdump` | Timeout = dropped (firewall); RST = refused |
| Does TLS succeed? | 6 | `openssl s_client` | Cert expired, wrong name, version mismatch |
| Does the session stay up? | 5 | proxy / LB logs | Idle timeout, NAT mapping expiry |
| Does the application answer correctly? | 7 | `curl -v`, app logs | 4xx / 5xx — this is finally app code |

Rules of thumb:

- A **timeout** is usually a lower-layer problem (packets dropped). A **refusal** or an **error code** means lower layers worked.
- A failed `ping` is not proof — many networks block ICMP while TCP 443 works.
- A **running process is not a working path**. Listen address, firewall, route, and NAT all sit between them.

---

## 6) Reliability, security, and ops lens

| Layer | Typical reliability control | Typical security control | What to monitor |
| --- | --- | --- | --- |
| 1 | Redundant links, diverse paths | Physical access control | Link flaps, CRC errors, signal strength |
| 2 | Link aggregation, STP | Port security, 802.1X, VLAN separation | MAC table churn, ARP anomalies |
| 3 | Redundant routers, ECMP, BGP | ACLs, private subnets, anti-spoofing | Packet loss, latency, route changes |
| 4 | Retransmission, connection pooling | Stateful firewalls, SYN cookies | Retransmit rate, resets, SYN backlog |
| 5 | Session resumption, heartbeats | Session expiry, token rotation | Idle disconnects, session churn |
| 6 | Compression, efficient encoding | TLS, certificate management | Handshake failures, cert expiry |
| 7 | Retries, caching, load balancing | WAF, auth, rate limits | Error rates, latency, status codes |

---

## 7) Key takeaways

- Each layer has **one job** and only reads its own header.
- **Encapsulation** wraps data going down; **decapsulation** unwraps it going up — on every host and, up to layer 3, on every router.
- OSI is the **vocabulary**; TCP/IP is what runs. Layers 5–7 collapse into "application" in practice.
- **MAC changes every hop; IP stays end to end** (unless NAT rewrites it).
- Troubleshoot **layer by layer**: a timeout points low, an error code points high.

---

## 8) Quick glossary

- **PDU (protocol data unit):** The unit a layer works with — bit, frame, packet, segment, message.
- **Encapsulation:** Adding a header around the data from the layer above.
- **Decapsulation:** Removing that header on receipt.
- **Header / trailer:** Control information added before / after the payload.
- **Peer layer:** The same layer on the other machine, which reads the header you wrote.
- **TCP/IP model:** The four-layer stack the internet actually uses.
- **Middlebox:** A device on the path (NAT, firewall, proxy) that inspects or rewrites traffic.

---

## 9) Sources & further reading

- ISO/IEC 7498-1 — *OSI Basic Reference Model*: <https://www.iso.org/standard/20269.html>
- ITU-T X.200 — *OSI Basic Reference Model* (freely available text): <https://www.itu.int/rec/T-REC-X.200-199407-I/en>
- RFC 1122 — *Requirements for Internet Hosts — Communication Layers*: <https://www.rfc-editor.org/rfc/rfc1122>
- RFC 3439 — *Some Internet Architectural Guidelines* ("layering considered harmful"): <https://www.rfc-editor.org/rfc/rfc3439>
- Cloudflare — *What is the OSI model?*: <https://www.cloudflare.com/learning/ddos/glossary/open-systems-interconnection-model-osi/>
- MDN — *How does the internet work?*: <https://developer.mozilla.org/en-US/docs/Learn_web_development/Howto/Web_mechanics/How_does_the_Internet_work>
- Cloud X Berry — *Networking topics every developer should know* (video): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
