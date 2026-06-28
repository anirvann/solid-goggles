# Networking Layers (OSI + Practical View) — Detailed Notes

> Companion deep-dive for the summary diagram: `networking-layers-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand how data moves from an application down to the physical wire (and back), what each layer is responsible for, and how the theoretical OSI model maps to the protocols actually used on the Internet.

---

## 1) Big picture

Networking is organized into **layers**. Each layer:

- Has a single, well-defined responsibility.
- Talks only to the layer directly above and below it.
- Adds its own **header** (and sometimes trailer) to the data as it goes down the stack — a process called **encapsulation** — and removes it on the way up (**decapsulation**).

Two models matter:

| Model | Layers | Use |
| --- | --- | --- |
| **OSI** | 7 layers | Conceptual teaching/reference model |
| **TCP/IP (Internet)** | 4 layers | What the Internet actually runs on |

---

## 2) The 7 OSI layers (top → bottom)

### Layer 7 — Application
- **Purpose:** Interface to the end-user application; defines protocols apps use.
- **Examples:** HTTP, HTTPS, DNS, SMTP, FTP, SSH.
- **Data unit:** Data / message.
- **Mental model:** "What the user/app wants to do."

### Layer 6 — Presentation
- **Purpose:** Data translation, encoding, compression, and **encryption** (e.g., TLS is often placed here).
- **Examples:** TLS/SSL, character encoding (UTF-8, ASCII), JPEG/PNG, serialization.
- **Mental model:** "Make sure both sides understand the format."

### Layer 5 — Session
- **Purpose:** Establishes, manages, and terminates sessions/dialogs between applications.
- **Examples:** Session setup/teardown, authentication sessions, RPC sessions.
- **Mental model:** "Who is talking to whom, and for how long."

### Layer 4 — Transport
- **Purpose:** End-to-end delivery between processes; segmentation, reliability, flow control. **Ports live here.**
- **Examples:** TCP (reliable), UDP (fast/unreliable).
- **Data unit:** Segment (TCP) / Datagram (UDP).
- **Mental model:** "Deliver to the right application reliably (or quickly)."

### Layer 3 — Network
- **Purpose:** Logical addressing and **routing** of packets across networks.
- **Examples:** IP (IPv4/IPv6), ICMP, routing protocols (OSPF, BGP).
- **Data unit:** Packet.
- **Mental model:** "Find a path from source IP to destination IP."

### Layer 2 — Data Link
- **Purpose:** Node-to-node delivery on the same physical network; **frames** and **MAC addresses**; error detection.
- **Examples:** Ethernet, Wi-Fi (802.11), ARP, switches.
- **Data unit:** Frame.
- **Mental model:** "Move bits between directly connected devices."

### Layer 1 — Physical
- **Purpose:** Transmission of raw bits over a medium (electrical, optical, radio).
- **Examples:** Cables, fiber, radio signals, hubs, voltages.
- **Data unit:** Bits.
- **Mental model:** "The actual signals on the wire/air."

---

## 3) Practical Internet (TCP/IP) stack mapping

The OSI model is conceptual. Real-world networking uses the 4-layer TCP/IP model:

| TCP/IP layer | OSI equivalent | Examples |
| --- | --- | --- |
| **Application** | 5, 6, 7 | HTTP, HTTPS, DNS, TLS |
| **Transport** | 4 | TCP, UDP |
| **Internet** | 3 | IP, ICMP |
| **Link** | 1, 2 | Ethernet, Wi-Fi, ARP |

Key mappings to remember:
- **Ports live at Transport** (e.g., 80, 443).
- **Routing happens at the Network/Internet layer** (IP addresses).
- **Frames and MAC addressing happen at Data Link.**

---

## 4) Packet journey (high level)

A simplified request from a browser to a server:

```
Browser request (HTTP)
   ↓ encapsulate
TCP segment   (adds source/destination ports, sequence numbers)
   ↓
IP packet     (adds source/destination IP, TTL)
   ↓
Ethernet frame(adds source/destination MAC, error check)
   ↓
Wire / Wi-Fi  (raw bits)
   ↓
Router        (reads IP, forwards toward destination)
   ↓
Server        (decapsulates back up the stack)
```

On the receiving side the process runs in reverse (decapsulation): each layer strips its header and hands the payload up.

> A more detailed version (with TLS, NAT, and header nesting) is covered in
> [`02-transport-ip-secure-web.md`](./02-transport-ip-secure-web.md).

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ping <host>` | Reachability + round-trip time (uses ICMP, Layer 3). |
| `traceroute <host>` (Linux/macOS) / `tracert` (Windows) | Each router hop along the path. |
| `netstat -tunap` (Linux) / `netstat -ano` (Windows) | Active connections, listening ports. |
| `ss -tunap` (modern Linux) | Faster replacement for `netstat`. |
| `ip addr` / `ifconfig` | Local interface addresses (IP + MAC). |
| `arp -a` | MAC ↔ IP mappings on the local network (Layer 2). |

---

## 6) Key takeaways

- Layering = separation of concerns; each layer trusts the one below it.
- **Encapsulation** wraps data with headers going down; **decapsulation** unwraps going up.
- OSI is the teaching model; TCP/IP is the operational model.
- Remember the anchors: **ports → transport**, **routing → network**, **frames → data link**.

---

## 7) Sources & further reading

- RFC 1122 — *Requirements for Internet Hosts (Communication Layers)*: <https://www.rfc-editor.org/rfc/rfc1122>
- ISO/IEC 7498-1 — *OSI Basic Reference Model*: <https://www.iso.org/standard/20269.html>
- Cloudflare Learning — *What is the OSI Model?*: <https://www.cloudflare.com/learning/ddos/glossary/open-systems-interconnection-model-osi/>
- Cloudflare Learning — *What is the network layer?*: <https://www.cloudflare.com/learning/network-layer/what-is-the-network-layer/>
- MDN — *How the web works*: <https://developer.mozilla.org/en-US/docs/Learn/Common_questions/Web_mechanics/How_does_the_Internet_work>
- IBM — *OSI model*: <https://www.ibm.com/think/topics/osi-model>
