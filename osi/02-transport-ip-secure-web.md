# Transport, IP & Secure Web: Deep Dive — Detailed Notes

> Companion deep-dive for the summary diagram: `tcp-udp-tls-packet-journey.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the transport protocols (TCP/UDP), the network addressing schemes (IPv4/IPv6), how HTTPS/TLS secures traffic (handshake + certificates), and the **full encapsulated packet journey** from browser to server and back.

---

## 1) TCP vs UDP

Both run at the **transport layer** and use **ports** to deliver data to the right process.

| Feature | TCP | UDP |
| --- | --- | --- |
| Connection | Connection-oriented (handshake first) | Connectionless |
| Reliability | Guaranteed delivery, retransmits lost data | No guarantee |
| Ordering | In-order delivery (sequence numbers) | No ordering |
| Flow/congestion control | Yes | No |
| Overhead | Higher (20+ byte header) | Lower (8-byte header) |
| Speed | Slower, but reliable | Faster, lightweight |
| Typical uses | HTTP(S), SSH, email, file transfer | DNS, VoIP, video streaming, gaming, QUIC |

**When to choose which:**
- Use **TCP** when correctness matters more than latency (web pages, APIs, file downloads).
- Use **UDP** when speed/low latency matters and you can tolerate (or handle) loss (live video, games, DNS lookups).

### TCP 3-way handshake

Before any data flows, TCP establishes a connection:

```
Client  ── SYN (seq=x) ─────────────▶  Server
Client  ◀── SYN-ACK (seq=y, ack=x+1) ─ Server
Client  ── ACK (ack=y+1) ───────────▶  Server
        ── [connection established] ──
            ... data transfer ...
```

**Connection teardown** (graceful close) uses a 4-way exchange:

```
FIN ▶   ◀ ACK   ◀ FIN   ACK ▶
```

- **SYN** = synchronize sequence numbers.
- **ACK** = acknowledge received data.
- **FIN** = no more data to send.

---

## 2) IPv4 vs IPv6

Both run at the **network layer** and provide logical addressing + routing.

| Feature | IPv4 | IPv6 |
| --- | --- | --- |
| Address size | 32-bit | 128-bit |
| Format | Dotted decimal: `192.168.1.1` | Hex, colon-separated: `2001:db8::1` |
| Address space | ~4.3 billion | ~3.4 × 10^38 (effectively unlimited) |
| NAT | Commonly required (address scarcity) | Not needed (every device can be global) |
| Header | Variable, more fields | Simplified, fixed 40-byte base header |
| Config | Manual or DHCP | SLAAC (autoconfiguration) or DHCPv6 |
| Security | IPsec optional | IPsec designed-in (optional in practice) |

**Notes:**
- IPv6 shorthand: consecutive zero groups can collapse to `::` (only once per address).
- Loopback: IPv4 `127.0.0.1`, IPv6 `::1`.
- Both coexist via **dual-stack** deployments.

---

## 3) HTTPS / TLS handshake

HTTPS = HTTP over **TLS** (Transport Layer Security). TLS provides:
- **Confidentiality** (encryption),
- **Integrity** (tamper detection),
- **Authentication** (you're talking to the real server, via certificates).

### TLS 1.3 handshake (simplified)

```
Client ── ClientHello (supported ciphers, key share) ──────▶ Server
Client ◀─ ServerHello (chosen cipher, key share)            ─ Server
Client ◀─ Certificate + Finished (encrypted)                ─ Server
Client ── Finished (encrypted) ────────────────────────────▶ Server
        ── [secure channel established] ──
            ... encrypted application data ...
```

- **TLS 1.3** completes in **1 round trip (1-RTT)**, with **0-RTT** resumption possible.
- **TLS 1.2** required 2 round trips.
- Key exchange uses **(EC)DHE** for forward secrecy — past traffic stays safe even if the private key later leaks.

---

## 4) Certificates & trust

How the client knows the server is genuine:

1. The server presents an **X.509 certificate** containing its **public key** and domain name.
2. The certificate is **signed by a Certificate Authority (CA)** using the CA's private key.
3. The browser/OS ships with a list of **trusted root CAs**.
4. The client verifies the **certificate chain**: server cert → intermediate CA → trusted root.
5. Checks performed: domain match, expiry date, revocation status (CRL/OCSP), valid signature.
6. If valid → padlock shown; if not → warning.

**Key concepts:**
- **Asymmetric crypto:** public key encrypts / verifies, private key decrypts / signs.
- **Chain of trust:** trust flows from a root CA down to the server certificate.
- **Validation levels:** DV (domain), OV (organization), EV (extended).
- Free automated certs are widely available via **Let's Encrypt** (ACME protocol).

---

## 5) Packet journey (detailed, with encapsulation)

Each layer **wraps** the payload from the layer above with its own header. Visually, headers nest like envelopes inside envelopes:

```
[ Ethernet header [ IP header [ TCP header [ TLS record [ HTTP request ] ] ] ] ] + Ethernet trailer
```

### Outbound (browser → server)

1. **HTTP request** is created by the browser (application layer).
2. **TLS** encrypts the request into a TLS record (presentation/app layer).
3. **TCP** wraps it in a segment — adds **source/destination ports** + **sequence/ack numbers**.
4. **IP** wraps it in a packet — adds **source/destination IP** + **TTL**.
5. **Ethernet/Wi-Fi** wraps it in a frame — adds **source/destination MAC** + error-check trailer.
6. **NIC** converts the frame to **bits** on the wire/Wi-Fi (physical layer).
7. **Switch** forwards based on MAC (Layer 2) within the local network.
8. **Router** reads the **IP** header, decrements TTL, performs **NAT** if needed, and forwards toward the destination network (Layer 3). This repeats hop by hop across ISPs.
9. **Server NIC** receives the bits and reassembles the frame.

### Inbound (decapsulation at server)

Each layer strips its header and passes the payload up:

```
bits → frame (strip Ethernet) → packet (strip IP) → segment (strip TCP)
     → TLS decrypt → HTTP request → handed to the web server
```

The **response** then makes the same journey in reverse back to the browser.

> **NAT note:** With IPv4, the router often rewrites the private source IP/port to a public one and tracks the mapping so the response can be routed back to the right internal device. IPv6 generally removes the need for NAT.

---

## 6) Hands-on commands

| Command | What it shows |
| --- | --- |
| `dig <domain>` / `nslookup <domain>` | DNS resolution (name → IP). |
| `curl -v https://example.com` | Full request/response incl. TLS handshake details. |
| `openssl s_client -connect example.com:443` | Inspect the server certificate + TLS negotiation. |
| `openssl x509 -in cert.pem -text -noout` | Decode a certificate's fields. |
| `tcpdump -i any port 443` | Capture packets on the wire (needs privileges). |
| `ss -tn` | Active TCP connections + state. |

---

## 7) Key takeaways

- **TCP = reliable/ordered; UDP = fast/lightweight.** Pick based on latency vs correctness needs.
- **IPv6 exists to solve IPv4 exhaustion** and remove the need for NAT.
- **TLS gives confidentiality + integrity + authentication**; TLS 1.3 is faster (1-RTT) and safer.
- **Certificates + CA chain of trust** are what make HTTPS trustworthy.
- The packet journey is **nested encapsulation** going down and **decapsulation** going up — at every hop.

---

## 8) Sources & further reading

**Transport (TCP/UDP)**
- RFC 9293 — *Transmission Control Protocol (TCP)*: <https://www.rfc-editor.org/rfc/rfc9293>
- RFC 768 — *User Datagram Protocol (UDP)*: <https://www.rfc-editor.org/rfc/rfc768>
- Cloudflare — *TCP vs UDP*: <https://www.cloudflare.com/learning/ddos/glossary/user-datagram-protocol-udp/>

**IP addressing**
- RFC 791 — *Internet Protocol (IPv4)*: <https://www.rfc-editor.org/rfc/rfc791>
- RFC 8200 — *Internet Protocol, Version 6 (IPv6)*: <https://www.rfc-editor.org/rfc/rfc8200>
- Cloudflare — *What is IPv6?*: <https://www.cloudflare.com/learning/network-layer/what-is-ipv6/>

**TLS / HTTPS / certificates**
- RFC 8446 — *TLS 1.3*: <https://www.rfc-editor.org/rfc/rfc8446>
- MDN — *Transport Layer Security (TLS)*: <https://developer.mozilla.org/en-US/docs/Web/Security/Transport_Layer_Security>
- Cloudflare — *What happens in a TLS handshake?*: <https://www.cloudflare.com/learning/ssl/what-happens-in-a-tls-handshake/>
- Cloudflare — *What is an SSL certificate?*: <https://www.cloudflare.com/learning/ssl/what-is-an-ssl-certificate/>
- Let's Encrypt — *How it works*: <https://letsencrypt.org/how-it-works/>

**NAT & packet flow**
- RFC 2663 — *NAT terminology*: <https://www.rfc-editor.org/rfc/rfc2663>
- Cloudflare — *What is NAT?*: <https://www.cloudflare.com/learning/network-layer/what-is-nat/>
