# Local Delivery, Routing, NAT & Subnets — Detailed Notes

> Companion deep-dive for the summary diagram: `local-routing-nat-subnets-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (chapters 04–09, about 6:48–12:17).

**Learning goal:** Explain how a RideNow request crosses the passenger's local network, hops between routers, shares a public address through NAT, and lands in the right subnet — including how DHCP configured the phone in the first place.

Previous: [addressing, DNS, and ports](./01-addressing-dns-and-ports.md). The packet already has a destination IP and port. It still has to move.

---

## 1) Big picture

The phone knows the RideNow IP. RideNow is not on the home Wi-Fi. Four mechanisms cover the gap:

| Piece | Problem it solves | RideNow moment |
| --- | --- | --- |
| **MAC address** | Which interface on *this* link should receive the frame? | Phone → home router over Wi-Fi |
| **ARP** | What is the MAC for this local IPv4 address? | "Who has the gateway?" |
| **Routing** | Which next hop moves the packet toward the destination network? | Home router → ISP → RideNow |
| **NAT** | How does a private source address talk through one public address? | Phone `192.168.1.42` leaves the house |
| **Subnetting** | How do we split RideNow into segments we can control? | Edge, app tier, database tier |
| **DHCP** | How does a new device learn IP, gateway, and DNS without a human? | Phone joins Wi-Fi; a new VM joins a subnet |

The phone does **not** know the full path. Each router only chooses the next hop.

---

## 2) MAC addresses

A **MAC address** identifies a network interface on a local link (Ethernet, Wi-Fi). It is burned into or assigned to the NIC, usually 48 bits, written like `3c:22:fb:a1:09:c4`.

Keep the two addresses apart:

| | IP | MAC |
| --- | --- | --- |
| Scope | Across networks | This local link only |
| Changes when | The device joins a different network | Rarely (the interface stays) |
| Used by | Routers, as the packet's destination | Switches and the local NIC, as the frame's destination |
| RideNow | `203.0.113.10:443` is the API | The Wi-Fi radio of the home router is the first hop |

IP is the logical destination across the internet. MAC is how the frame reaches the next device on the same wire or radio.

---

## 3) ARP (IPv4)

The phone has the gateway's IP (from DHCP) and needs the gateway's MAC. **ARP**, Address Resolution Protocol, asks on the local link:

```
Phone  → broadcast:  "Who has 192.168.1.1? Tell 192.168.1.42"
Router → unicast:    "192.168.1.1 is at 3c:22:fb:a1:09:c4"
Phone caches the mapping and sends the frame.
```

The cache avoids asking on every packet. A stale entry (router replaced, VM migrated, Wi-Fi roam) sends frames to a MAC nobody owns, and the conversation silently dies until the entry expires or is cleared.

ARP is an **IPv4** tool. IPv6 uses **Neighbor Discovery** (RFC 4861) for the same job. You will not think about ARP while coding a ride request. You will think about it when two hosts on the same subnet cannot talk and `ip neigh` shows `FAILED`.

---

## 4) Routing

Once the frame reaches the home router, the router strips it and looks at the **destination IP**. Its routing table says which interface and next hop get the packet closer to that network. The next router does the same. Repeat until a router is directly attached to the destination subnet.

Consequences:

- The path can cross many networks (home, ISP, transit, RideNow's cloud). Any hop can add latency or drop packets while the application itself is healthy.
- Each IPv4 hop decrements **TTL**. At zero the packet is discarded and ICMP Time Exceeded is sent. That is how `traceroute` draws the path.
- The return path can differ from the forward path. Asymmetric routing makes "I see the request in one capture and not the reply" a normal debugging state.

---

## 5) NAT

The phone's source address is private. The internet has no route back to `192.168.1.42`. **NAT** (in the form home routers actually implement, **NAPT / PAT**) rewrites the source as the packet leaves:

```
Before NAT:   192.168.1.42:51432  →  203.0.113.10:443
After NAT:    203.0.113.50:40001  →  203.0.113.10:443
Router remembers:  public 203.0.113.50:40001  ↔  phone 192.168.1.42:51432
```

The reply arrives at `203.0.113.50:40001`. The mapping tells the router which internal socket gets it. Many devices share one public address because each flow gets its own public source port.

The same pattern shows up in cloud:

- Private app servers reach the internet for updates or a payment API through a **NAT gateway**.
- Unsolicited inbound packets have no mapping, so they are not delivered to those servers.
- That is outbound-only connectivity. It is not a full access policy. Firewalls still decide what is allowed ([note 04](./04-infrastructure-and-network-security.md)).

What breaks:

- **Port exhaustion.** Too many concurrent flows from one public IP, and new connections fail even though the app is fine.
- **Idle timeouts.** A NAT entry expires; the next packet of a quiet WebSocket or database pool is dropped. Keepalives exist for this reason.
- **Inbound to the phone.** The passenger's phone cannot host a public server on its private address without an explicit port forward, which RideNow does not need. The phone opens the connection outward.

---

## 6) Subnetting

A **subnet** is a slice of a larger network: a prefix (CIDR) plus the hosts that share it. Hosts in the same subnet deliver directly (ARP / NDP). Hosts in a different subnet send to a gateway.

RideNow does not put every machine in one flat network. A useful split:

| Subnet | Who lives there | Who should talk to it |
| --- | --- | --- |
| Public edge | Load balancer, reverse proxy | Passengers on the internet, on 443 |
| Application | Passenger, driver, and trip services | The edge, and each other as designed |
| Data | Databases, caches | Application subnet only, on the DB port |

The mask creates the boundary (what is "local"). **Routing plus firewalls** decide which boundaries may be crossed. A subnet alone does not block a packet; a route into that subnet plus an allow rule does the real filtering. The point of the split is to *have* a place to attach those rules, so the database is not on the same segment as the public edge.

Sizing matters operationally. A `/24` has 256 addresses (254 usable in the classic IPv4 layout). Cloud subnets that also spend addresses on load balancers and reserved IPs run out during a scale-out. Plan the prefix before the launch, not during it.

---

## 7) DHCP

**DHCP** gives a device its network configuration automatically. The phone joining Wi-Fi, and a new RideNow VM joining a subnet, both use it.

The IPv4 exchange (DORA):

```
Discover  (broadcast)  "I need a configuration"
Offer                    "You can have 192.168.1.42"
Request                  "I'll take 192.168.1.42"
Ack                      "Lease granted" + options
```

The options that matter:

- IP address and subnet mask
- Default gateway (the router ARP will look up)
- DNS servers (so the hostname lookup in [note 01](./01-addressing-dns-and-ports.md) has someone to ask)
- Lease time (the address is borrowed, then renewed)

Static configuration is appropriate for a handful of infrastructure addresses (the gateway, the DNS resolver, sometimes the database). It does not scale to every phone and every autoscaled instance.

---

## 8) End-to-end: from the phone to the RideNow subnet

```
1. DHCP already gave the phone
   IP 192.168.1.42, mask /24, gateway 192.168.1.1, DNS 192.168.1.1
2. DNS resolved api.ridenow.example → 203.0.113.10   (note 01)
3. 203.0.113.10 is NOT in 192.168.1.0/24, so the next hop is the gateway
4. ARP: who has 192.168.1.1? → MAC of the home router
5. Frame to that MAC; IP packet still says dest 203.0.113.10:443
6. Home router NAT: source becomes 203.0.113.50:40001, mapping stored
7. ISP routers forward hop by hop toward 203.0.113.0/24
8. RideNow edge subnet receives the packet on the public address
9. Reply follows the NAT mapping back to 192.168.1.42:51432
```

Risks along that strip: stale ARP, wrong default gateway, NAT mapping expired, a missing route to the RideNow prefix, or a subnet so small the new app server never got an address from DHCP.

---

## 9) Reliability, security, and ops

- **A healthy app and a broken path coexist.** Trace the hops before you redeploy the service. Loss at hop 7 is not a bug in the ride handler.
- **NAT timeouts must exceed your idle connections.** Database pools and driver-location WebSockets need keepalive or a longer mapping.
- **Watch NAT port allocation** on cloud NAT gateways. Exhaustion looks like random connect failures.
- **Subnet IP exhaustion** shows up as instance launch failures, not as HTTP 500s.
- **DHCP lease exhaustion** or a rogue DHCP server hands out addresses that then collide or point at the wrong gateway.
- **Security boundary:** private subnets plus NAT reduce unsolicited inbound reachability. Security groups and firewalls are still the allow-list ([note 04](./04-infrastructure-and-network-security.md)).

---

## 10) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ip route` / `ip route get 203.0.113.10` | Which gateway this host will use. |
| `ip neigh` / `arp -a` | IPv4-to-MAC cache. `FAILED` means ARP got no answer. |
| `traceroute -n api.ridenow.example` | Each hop, and where latency or loss starts. |
| `tracepath` | Same idea, plus MTU discovery along the path. |
| `ip addr show` | Address, prefix length, and whether DHCP put it there. |

---

## 11) Key takeaways

- **MAC** delivers a frame on the local link. **IP** is the address routers use across networks.
- **ARP** fills in the MAC for a local IPv4 address and caches it. IPv6 uses NDP instead.
- **Routing** is hop by hop. The phone never carries the full path, so a mid-path problem is invisible to the app process.
- **NAT** rewrites a private source to a public address and port, and remembers the mapping so the reply finds the phone.
- **Subnets** create segments (edge, app, data). Routes and firewalls enforce them.
- **DHCP** supplies IP, mask, gateway, and DNS so nobody types that by hand.

---

## 12) Quick glossary

- **MAC address:** Link-layer identity of a network interface.
- **ARP:** IPv4 broadcast that resolves a local IP to a MAC.
- **NDP:** IPv6 Neighbor Discovery; the equivalent job to ARP.
- **Default gateway:** Router used for destinations outside the local subnet.
- **TTL:** Hop limit in the IP header. Routers decrement it.
- **NAT / NAPT:** Rewrite of source (or destination) address; NAPT also rewrites the port so many hosts share one public IP.
- **CIDR / subnet:** A prefix such as `10.0.2.0/24` that groups hosts into one segment.
- **DHCP:** Protocol that leases a host its network configuration.
- **DORA:** Discover, Offer, Request, Ack — the IPv4 DHCP handshake.

---

## 13) Sources & further reading

- RFC 826 — *An Ethernet Address Resolution Protocol*: <https://www.rfc-editor.org/rfc/rfc826>
- RFC 4861 — *Neighbor Discovery for IPv6*: <https://www.rfc-editor.org/rfc/rfc4861>
- RFC 1812 — *Requirements for IP Version 4 Routers*: <https://www.rfc-editor.org/rfc/rfc1812>
- RFC 4632 — *CIDR*: <https://www.rfc-editor.org/rfc/rfc4632>
- RFC 2663 — *IP NAT terminology*: <https://www.rfc-editor.org/rfc/rfc2663>
- RFC 3022 — *Traditional IP NAT*: <https://www.rfc-editor.org/rfc/rfc3022>
- RFC 2131 — *Dynamic Host Configuration Protocol*: <https://www.rfc-editor.org/rfc/rfc2131>
- Cloudflare — *What is NAT?*: <https://www.cloudflare.com/learning/network-layer/what-is-nat/>
- Video chapters 04–09 (MAC, ARP, routing, NAT, subnetting, DHCP): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
