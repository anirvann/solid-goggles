# Layer 3 — Network — Detailed Notes

> Companion deep-dive for the summary diagram: `network-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand logical addressing (IPv4/IPv6, private vs public), how subnets divide networks, how routers forward packets hop by hop, and how NAT lets private hosts reach the internet.

---

## 1) Big picture

Layer 3 moves **packets from one host to another across many networks**. Layer 2 only reaches neighbors; layer 3 is what makes an *internetwork*.

Responsibilities:

- **Logical addressing:** IP addresses that describe where a host sits in the network.
- **Routing:** choosing the next hop toward the destination network.
- **Forwarding:** moving each packet out the chosen interface.
- **Fragmentation** (IPv4) when a packet is bigger than the next link's MTU.
- **Error reporting and diagnostics:** ICMP.

**PDU:** packet.

An IP address is a **location**, not a permanent identity. The same laptop gets a different address on home Wi-Fi, office Wi-Fi, and a phone hotspot.

---

## 2) Components

### IPv4 vs IPv6

| | IPv4 | IPv6 |
| --- | --- | --- |
| Size | 32-bit | 128-bit |
| Notation | Dotted decimal `203.0.113.10` | Hex groups `2001:db8::10` |
| Address space | ~4.3 billion | 2¹²⁸ (vastly larger) |
| Header | 20–60 bytes, has checksum | Fixed 40-byte base, no checksum |
| Fragmentation | Routers or sender | Sender only |
| Configuration | DHCP or static | SLAAC, DHCPv6, or static |
| Neighbor resolution | ARP (L2) | NDP (ICMPv6) |
| NAT | Common (address scarcity) | Rarely needed |
| Loopback | `127.0.0.1` | `::1` |

IPv6 shorthand: leading zeros in a group can be dropped, and **one** run of all-zero groups can become `::`. Most networks run **dual-stack**.

### Private vs public addresses

| Type | Range | Routable on the internet? |
| --- | --- | --- |
| Private (RFC 1918) | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | No |
| Carrier-grade NAT (RFC 6598) | `100.64.0.0/10` | No (ISP-internal) |
| Link-local | `169.254.0.0/16`, `fe80::/10` | No (one link only) |
| IPv6 unique local | `fc00::/7` | No |
| Loopback | `127.0.0.0/8`, `::1` | No (this host only) |
| Public | Everything globally assigned | Yes |

Private addresses can be reused in every home and every cloud VPC. To reach the internet they need **NAT**; to be reached they need a public address in front (a load balancer, a proxy, or a port forward).

### Subnetting and CIDR

An address plus a **prefix length** defines a subnet: `192.168.1.0/24` = the first 24 bits are the network, the last 8 identify hosts.

| Prefix | Mask | Addresses | Usable hosts (IPv4) |
| --- | --- | --- | --- |
| /16 | 255.255.0.0 | 65,536 | 65,534 |
| /24 | 255.255.255.0 | 256 | 254 |
| /26 | 255.255.255.192 | 64 | 62 |
| /28 | 255.255.255.240 | 16 | 14 |
| /30 | 255.255.255.252 | 4 | 2 |
| /32 | 255.255.255.255 | 1 | single host route |

(Usable = total minus network and broadcast addresses. Cloud providers often reserve a few more per subnet.)

**Why subnet?**

- **Organization:** group hosts by role (public-facing, application, database).
- **Control:** create boundaries where routing rules and firewalls apply.
- **Efficiency:** smaller broadcast domains.

A typical three-tier layout:

```
VPC 10.0.0.0/16
├── public subnet   10.0.1.0/24   load balancers, NAT gateway
├── app subnet      10.0.2.0/24   application servers
└── data subnet     10.0.3.0/24   databases — no route from the internet
```

**Same subnet or not?** A host ANDs the destination with its own mask. Same network → deliver directly (ARP for the host). Different → send to the **default gateway**.

### Routing

A router keeps a **routing table** of destination prefixes → next hop / interface. For each packet:

1. Read the destination IP.
2. Find the **longest prefix match** in the table.
3. Decrement **TTL** (IPv4) / **hop limit** (IPv6). If it hits zero, drop and send ICMP Time Exceeded.
4. Build a new layer-2 frame for the outgoing link and forward.

Route sources:

- **Connected:** subnets directly on the router's interfaces.
- **Static:** configured by hand (including the default route `0.0.0.0/0`).
- **Dynamic:** learned from protocols — **OSPF/IS-IS** inside an organization, **BGP** between organizations (the internet's routing protocol).

No host knows the full path. Each router only picks the next hop, so the forward and return paths can differ.

### NAT (Network Address Translation)

The common home/cloud form is **NAPT** (also called PAT or "masquerade"): many private hosts share one public IP by also rewriting the source port.

```
Outbound   192.168.1.42:51432 → 198.51.100.10:443
After NAT  203.0.113.50:40001 → 198.51.100.10:443
Table      203.0.113.50:40001 ↔ 192.168.1.42:51432
Reply      198.51.100.10:443 → 203.0.113.50:40001 → rewritten back to 192.168.1.42:51432
```

Variants:

- **SNAT / source NAT:** outbound (home routers, cloud NAT gateways).
- **DNAT / destination NAT / port forwarding:** inbound to a private host.
- **CGNAT:** the ISP does another layer of NAT.

NAT allows outbound connectivity and blocks unsolicited inbound *as a side effect*. It is **not a firewall** — use explicit firewall rules for access control.

### ICMP

The network layer's control and error protocol:

- **Echo request/reply** — `ping`.
- **Time Exceeded** — what `traceroute` uses.
- **Destination Unreachable** — "no route," "port unreachable," "fragmentation needed."
- **ICMPv6** also carries Neighbor Discovery and is essential for IPv6 to work. Don't block it wholesale.

### DHCP (configuring layer 3)

DHCP is an application-layer protocol (UDP 67/68) whose job is to hand out layer-3 configuration: IP, mask, default gateway, DNS servers, lease time. Details in [`07-application-layer.md`](./07-application-layer.md).

---

## 3) End-to-end flow: one packet across the internet

```
Host 192.168.1.42/24 → 198.51.100.10
1. Not on 192.168.1.0/24 → send to gateway 192.168.1.1 (ARP for its MAC)
2. Home router: NAT source → 203.0.113.50:40001; TTL 64 → 63
3. ISP router: longest prefix match → next hop; TTL 62
4. ...BGP-learned routes across several autonomous systems...
5. Destination network's edge router → destination subnet
6. Last router ARPs for 198.51.100.10 and delivers the frame
7. Reply goes back to 203.0.113.50:40001; home router un-NATs it
```

---

## 4) Reliability, security, and ops

**Failure modes:**

- **No route / wrong default gateway** → "network unreachable" or a black hole.
- **Asymmetric routing** through a stateful firewall → replies dropped.
- **MTU / PMTUD black hole:** ICMP "fragmentation needed" blocked → large packets silently vanish.
- **NAT port exhaustion** → random new-connection failures from busy hosts.
- **NAT idle timeout** → long-lived quiet connections dropped. Use keepalives.
- **Subnet too small** → new instances can't get an address during scale-out.
- **Overlapping private ranges** between VPCs or offices → can't peer or VPN them.
- **BGP misconfiguration / route leaks** → large-scale outages.

**Reliability controls:** redundant gateways (VRRP/HSRP), ECMP across multiple paths, dynamic routing with fast convergence, multiple availability zones with separate subnets.

**Security:**

- Keep sensitive systems in **private subnets** with no inbound route.
- **ACLs / security groups** at subnet and instance boundaries (see [`08-devices-and-security-across-layers.md`](./08-devices-and-security-across-layers.md)).
- **Anti-spoofing** (uRPF / BCP 38): drop packets with impossible source addresses.
- **IPsec** for encrypted site-to-site tunnels.

**What to monitor:** packet loss and latency per hop, route table changes, BGP session state, NAT gateway port allocation, subnet free IPs, ICMP unreachable rates.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ip addr` | Host IP addresses and prefix lengths |
| `ip route` | Routing table and default gateway |
| `ip route get 198.51.100.10` | Which route and source IP a destination will use |
| `ping -c 4 host` | ICMP reachability and RTT |
| `traceroute -n host` / `mtr host` | Each hop, loss and latency |
| `tracepath host` | Path MTU discovery |
| `ipcalc 10.0.2.0/24` | Subnet math |
| `curl ifconfig.me` | Your public (post-NAT) address |

---

## 6) Key takeaways

- Layer 3 is **host-to-host across networks**: IP addressing plus routing.
- **IPv4 is 32-bit, IPv6 is 128-bit**; same job, IPv6 removes scarcity.
- **Private** addresses work inside a network; **public** addresses are reachable on the internet.
- **Subnets** (CIDR) split networks into segments you can route and filter.
- **Routers** use longest prefix match and forward hop by hop; nobody knows the full path.
- **NAT** lets private hosts share a public IP — it is not a security policy.

---

## 7) Quick glossary

- **IP address:** Logical layer-3 address of an interface.
- **CIDR / prefix length:** `/24` notation for how many bits are the network part.
- **Subnet mask:** Same idea in dotted form (`255.255.255.0`).
- **Default gateway:** Router used for destinations outside the local subnet.
- **Routing table:** Prefix → next hop mapping.
- **Longest prefix match:** The most specific matching route wins.
- **TTL / hop limit:** Counter decremented by each router to stop loops.
- **NAT / NAPT:** Rewriting addresses (and ports) at a boundary.
- **ICMP:** Control and error messages for IP.
- **BGP / OSPF:** Routing protocols between and within organizations.

---

## 8) Sources & further reading

- RFC 791 — *Internet Protocol (IPv4)*: <https://www.rfc-editor.org/rfc/rfc791>
- RFC 8200 — *IPv6 Specification*: <https://www.rfc-editor.org/rfc/rfc8200>
- RFC 1918 — *Address Allocation for Private Internets*: <https://www.rfc-editor.org/rfc/rfc1918>
- RFC 4632 — *Classless Inter-domain Routing (CIDR)*: <https://www.rfc-editor.org/rfc/rfc4632>
- RFC 1812 — *Requirements for IPv4 Routers*: <https://www.rfc-editor.org/rfc/rfc1812>
- RFC 3022 — *Traditional IP NAT*: <https://www.rfc-editor.org/rfc/rfc3022>
- RFC 792 — *ICMP*: <https://www.rfc-editor.org/rfc/rfc792>
- RFC 4271 — *BGP-4*: <https://www.rfc-editor.org/rfc/rfc4271>
- Cloudflare — *What is the network layer?*: <https://www.cloudflare.com/learning/network-layer/what-is-the-network-layer/>
- Cloudflare — *What is NAT?*: <https://www.cloudflare.com/learning/network-layer/what-is-nat/>
- AWS — *VPC subnets*: <https://docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html>
