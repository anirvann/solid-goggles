# One RideNow Request, Start to Finish — Detailed Notes

> Companion deep-dive for the summary diagram: `ridenow-request-journey-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (recap, about 22:50).

**Learning goal:** Walk a single "Request Ride" from the passenger's phone to the backend and back, and name which networking idea solves which problem at each step.

This is the spine of the folder. Each step links to the note that goes deep.

| Step | Note |
| --- | --- |
| Address, DNS, ports | [01](./01-addressing-dns-and-ports.md) |
| MAC, ARP, routing, NAT, subnets, DHCP | [02](./02-local-delivery-routing-nat.md) |
| TCP, TLS, HTTP, WebSockets, UDP | [03](./03-transport-and-application-protocols.md) |
| Load balancer, reverse proxy, firewall | [04](./04-infrastructure-and-network-security.md) |
| Where it breaks, by layer | [05](./05-osi-model-troubleshooting.md) |

---

## 1) The product moment

A passenger opens **RideNow**, enters a destination, and taps **Request Ride**. The system finds a driver. After the driver accepts, the passenger watches that car move on the map.

From the outside, that is one tap and a moving marker. Underneath, it is one request crossing every idea in this folder. Nothing here is a definition floating on its own. Each piece exists because the previous piece was not enough.

---

## 2) Component checklist

What has to be true before the tap works:

| Component | Must be true |
| --- | --- |
| Phone | Has an IP, a gateway, and a DNS resolver (DHCP) |
| DNS | `api.ridenow.example` answers with a live address, inside TTL |
| Path | ARP to the home gateway, NAT out, routes to RideNow's prefix |
| Edge | Firewall allows 443; proxy terminates TLS; balancer has a healthy app |
| App | Listens on the network, not only localhost; can reach the database |
| Data | Database accepts the app subnet and blocks the internet |
| After accept | WebSocket stays up so location pushes have a path |

---

## 3) End-to-end flow

### 1. Address the device

The phone receives an IP address, plus mask, gateway, and DNS, from **DHCP** when it joins Wi-Fi (or from the mobile network). That address is where the phone can be reached *on this network*, not a permanent name for the device. Home Wi-Fi and cellular are different addresses.

IPv4 is 32-bit. IPv6 is 128-bit. Both are answers to the same "where?" question. The home address is **private**. RideNow's front door is **public**.

### 2. Find the destination

**DNS** turns `api.ridenow.example` into an IP. Caches and **TTL** decide how long an old answer sticks around. One name can return several addresses.

The **port** then picks the service. `443` is the public API. The database port is a different service on a different machine, and it is not this destination.

### 3. Move through networks

On the Wi-Fi link, **MAC addresses** identify interfaces. **ARP** finds the gateway's MAC for its IPv4 address. The IP packet's destination stays "RideNow"; the frame's destination is only the next hop.

**Routers** forward hop by hop. The phone does not know the path. **NAT** on the home router rewrites the private source to a public address and port, and stores the mapping so the reply comes back to this phone. Inside RideNow, **subnets** separate the public edge, the application tier, and the databases.

### 4. Establish communication

**TCP** provides a reliable, ordered byte stream so a ride request cannot quietly lose a chunk and still look successful. The **three-way handshake** (SYN, SYN-ACK, ACK) opens that stream. RideNow reuses the connection for later calls instead of paying the handshake every time.

### 5. Secure and send the request

**TLS** encrypts the stream, detects tampering, and authenticates the server certificate before account or location data moves. **HTTP** then carries `POST /v1/rides`. The backend validates the passenger, checks the trip, looks for a driver, and sends the response.

### 6. Process the request behind the front door

A **firewall** allows the public internet to reach only the edge on 443. A **reverse proxy** terminates TLS, routes `/v1/rides` to the trip service, and can cache or compress where that is safe. A **load balancer** picks a healthy application server and stops using one that fails its health check. A second firewall allows the application subnet to open the database port and blocks everyone else, including the public internet.

If this step times out while the process looks healthy, suspect a dropped packet on one of those rules before suspecting the handler.

### 7. Deliver live updates

The driver accepts. Polling "where is the car?" every second wastes rounds when it has not moved. A **WebSocket** stays open in both directions, and the server **pushes** location as it changes. That socket still runs on TCP.

**UDP** is the other tool, for work where a lost sample should not stall the next one (a media leg, a small DNS query). It is not a faster replacement for the ride request. The request needed reliable delivery. The live sample sometimes needs freshness more than a perfect history.

---

## 4) The same path, as a strip

```
DHCP gives the phone an IP, gateway, DNS
        │
DNS → api.ridenow.example → public IP, port 443
        │
ARP gateway → frame to home router → NAT → route hop by hop
        │
TCP handshake → TLS → HTTP POST /v1/rides
        │
firewall → reverse proxy → load balancer → healthy app → firewall → database
        │
HTTP 201  (trip created)
        │
WebSocket upgrade → server pushes driver location
        │
UDP only if a side channel wants freshness over retransmission
```

The reply reverses the wrappers: database result, app response, proxy, NAT mapping, back to the phone's private socket.

---

## 5) Reliability, security, and ops

Use the strip as an incident checklist. Stop at the first step that is false.

| If you see | Stay on this step |
| --- | --- |
| Phone has no address, or the wrong gateway | 1 — DHCP |
| Some users still hit the old IP | 2 — DNS TTL |
| `traceroute` dies mid-path, or ARP fails | 3 — link, route, or NAT |
| SYN timeout or RST | 4 — handshake, listen address, or a drop |
| Certificate error, then no HTTP | 5 — TLS, before the handler |
| Proxy has no log line, app logs are quiet | 6 — firewall or routing to the front door |
| 502 / 504 from the proxy | 6 — balancer pool or the app itself |
| Map freezes, ride creation still works | 7 — WebSocket idle timeout, NAT, or draining |
| HTTP 401 / 422 | The path worked. This is application logic. |

Production controls that fall out of the same story:

- Scale and failure handling live at the **load balancer** and in health checks.
- Access control lives in **subnets and firewalls**, not in the hope that nobody knows the database IP.
- Confidentiality lives in **TLS**, at the edge and on any internal hop you do not trust.
- Connection reuse, WebSocket heartbeats, and NAT timeouts are **operations** problems that look like product bugs if you skip step 7.

---

## 6) Key takeaways

1. **Networking concepts solve different problems.** Addressing says where a device can be reached. DNS finds the destination. Ports pick the service. Routing moves packets between networks.
2. **Connectivity is not application health.** A running process can still be unreachable because of its listen address, a firewall, a route, a NAT timeout, or a stale DNS answer.
3. **Choose protocols for the requirement.** TCP carries the ride request reliably. UDP drops overhead when fresh beats complete. HTTP is request/response. WebSockets push live updates both ways.
4. **Production needs infrastructure controls.** Load balancers, reverse proxies, subnets, and firewalls are how RideNow stays available and keeps the database off the internet.
5. **Use the OSI model to troubleshoot in order.** Ask which layer failed. Do not treat "the network" as one mystery, and do not start in application code when the SYN never arrived.

---

## 7) Quick glossary

- **RideNow:** Fictional ride-sharing app used to keep every concept attached to one request.
- **Private IP:** Address used inside a local or cloud network, not routed on the public internet.
- **Public IP:** Address reachable across the internet. RideNow's edge has one; the phone usually does not.
- **NAT:** Translates the phone's private source so a shared public connection can carry the flow home.
- **Three-way handshake:** SYN, SYN-ACK, ACK. Opens a TCP connection.
- **Reverse proxy:** Front door that routes, terminates TLS, and hides internal services.
- **WebSocket:** Persistent two-way channel used to push driver location.
- **OSI model:** Seven-layer map for naming where a failure sits.

---

## 8) Sources & further reading

The narrative order comes from one video. The mechanisms come from the specs below, which the other notes cite in more detail.

- Cloud X Berry — *I Bet Nobody Has Ever Explained the Networking Topics Like This Before* (RideNow walkthrough): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
- RFC 1122 — *Requirements for Internet Hosts — Communication Layers*: <https://www.rfc-editor.org/rfc/rfc1122>
- RFC 9293 — *TCP*: <https://www.rfc-editor.org/rfc/rfc9293>
- RFC 8446 — *TLS 1.3*: <https://www.rfc-editor.org/rfc/rfc8446>
- RFC 9110 — *HTTP semantics*: <https://www.rfc-editor.org/rfc/rfc9110>
- RFC 6455 — *WebSocket*: <https://www.rfc-editor.org/rfc/rfc6455>
- RFC 1918 — *Private addresses*: <https://www.rfc-editor.org/rfc/rfc1918>
- ISO/IEC 7498-1 — *OSI Basic Reference Model*: <https://www.iso.org/standard/20269.html>

Chapter index for the video:

| Time | Chapter |
| --- | --- |
| 1:30 | IP address |
| 4:50 | DNS |
| 5:48 | Ports |
| 6:48 | MAC address |
| 7:39 | ARP |
| 8:30 | Routing |
| 9:17 | NAT |
| 10:18 | Subnetting |
| 11:16 | DHCP |
| 12:17 | TCP |
| 13:07 | Three-way handshake |
| 13:51 | HTTPS and TLS |
| 15:02 | HTTP |
| 15:41 | Load balancer |
| 16:33 | Reverse proxy |
| 17:40 | Firewall |
| 18:50 | WebSockets |
| 20:18 | UDP |
| 21:29 | OSI model |
| 22:50 | Recap: one request, start to finish |
