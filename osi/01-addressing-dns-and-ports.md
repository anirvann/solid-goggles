# Addressing, DNS & Ports — Detailed Notes

> Companion deep-dive for the summary diagram: `addressing-dns-ports-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (chapters 01–03, about 1:30–6:48).

**Learning goal:** Explain how a RideNow phone becomes addressable, how a hostname turns into an IP, and how a port selects the service — and why an application that is "up" can still be unreachable.

---

## 1) Big picture

RideNow is a fictional ride-sharing app. A passenger taps **Request Ride**. Before TCP, TLS, or HTTP matter, the network has to answer three questions:

1. **Where** can this phone be reached right now? → an **IP address**.
2. **Which** machine is `api.ridenow.example`? → **DNS**.
3. **Which** program on that machine should get the bytes? → a **port**.

An IP address is a **location**, not a permanent identity. The same phone has one address on home Wi-Fi and another on mobile data. A server can have several addresses, one per interface or network it joins.

Next note: how the packet actually leaves the house — [MAC, ARP, routing, NAT, subnets, DHCP](./02-local-delivery-routing-nat.md).

---

## 2) IPv4 and IPv6

Both versions solve the same problem: logical addressing so devices can send packets across IP networks. IPv6 exists because the IPv4 pool ran out once phones, servers, cloud VMs, and IoT devices all needed addresses.

| | IPv4 | IPv6 |
| --- | --- | --- |
| Size | 32-bit | 128-bit |
| Written as | Dotted decimal: `203.0.113.10` | Hex groups: `2001:db8::10` |
| Space | about 4.3 billion | 2^128, vastly larger |
| Typical host config | DHCP, or static | SLAAC, DHCPv6, or static |
| Header | Variable, 20–60 bytes | Fixed 40-byte base header |
| Local MAC discovery | ARP | Neighbor Discovery (NDP), not ARP |

Notes that matter in practice:

- IPv6 collapses one run of zero groups to `::` (once per address).
- Loopback is `127.0.0.1` (IPv4) and `::1` (IPv6).
- Many networks run **dual-stack**: the host has both an A record (IPv4) and an AAAA record (IPv6), and the client picks one (Happy Eyeballs, RFC 8305).

---

## 3) Private and public addresses

When the passenger joins home Wi-Fi, the phone usually receives a **private** address. That address is meaningful inside the local network. A host on the public internet cannot open a connection straight to `192.168.1.42`.

A **public** address is routable across the internet. RideNow's front door needs one (or a name that resolves to one). The database should not.

| Scope | IPv4 ranges (RFC 1918) | RideNow use |
| --- | --- | --- |
| Private | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | Phone on Wi-Fi, app servers, databases |
| Shared CGNAT | `100.64.0.0/10` (RFC 6598) | Often the address a phone sees on mobile data |
| Public | Everything else that is globally assigned | RideNow's internet-facing entry |
| IPv6 local | Unique local `fc00::/7`; link-local `fe80::/10` | Same idea: not a global destination |

This split is the reason later pieces exist:

- **NAT** lets the private phone talk *out* through a public address ([note 02](./02-local-delivery-routing-nat.md)).
- **Subnets and firewalls** keep the database off the public internet ([notes 02](./02-local-delivery-routing-nat.md) and [04](./04-infrastructure-and-network-security.md)).

---

## 4) DNS

The passenger never types an IP. The app uses a hostname. **DNS** translates that name into one or more addresses.

```
RideNow app
  → stub resolver (OS cache)
    → recursive resolver (ISP, or 1.1.1.1 / 8.8.8.8)
      → root → TLD (.example) → authoritative server
        → A / AAAA records
```

What the video's story depends on:

- **Caching.** The lookup is not repeated from scratch every tap. Caches sit in the app, the OS, and the recursive resolver.
- **TTL.** Each record carries a time to live. After it expires, the cache must ask again. A long TTL makes a record stable and cheap; it also makes a failover slow, because clients keep the old IP until the TTL drains.
- **Many addresses.** One hostname can return several A/AAAA records. That is how a name spreads clients across more than one machine before a load balancer is even in the path.

Failure modes developers actually hit:

| Symptom | Likely DNS cause | What to check |
| --- | --- | --- |
| Works for some users, not others | Split caches, or a resolver still holding the old TTL | `dig` from the failing network; compare TTL |
| New server never receives traffic | Record not published, or TTL not expired | Authoritative answer vs. cached answer |
| Intermittent connect to the wrong environment | Name points at several IPs, one of them bad | All addresses in the answer, not just the first |
| IPv6-only failure | AAAA published, v6 path broken | `dig AAAA`, then curl forcing `-4` |

---

## 5) Ports

An IP address identifies a machine (more precisely, an interface on a network). A **port** identifies the service on that machine. Ports are a 16-bit number: **1–65535**.

The usual analogy holds: the IP is the building, the port is the apartment.

| Port | Conventional service | RideNow |
| --- | --- | --- |
| 53 | DNS | Resolving `api.ridenow.example` |
| 80 | HTTP | Redirect to HTTPS, if anything |
| 443 | HTTPS | The public ride API |
| 3306 | MySQL | Database, private subnet only |
| 5432 | PostgreSQL | Same rule: not on the public edge |

The client also uses a port. The phone picks an **ephemeral** source port (typically from the dynamic range, 49152–65535) so the reply can be matched to the right socket. The server listens on the **well-known** destination port.

### Listening address: up is not reachable

A process can be running and still refuse the network. The **bind address** decides who may connect:

| Bind | Who can connect |
| --- | --- |
| `127.0.0.1` or `::1` | Only processes on that same machine |
| A specific private IP | Only traffic that arrives on that interface |
| `0.0.0.0` or `::` | Any interface on the host |

RideNow's API container that binds `127.0.0.1:443` is healthy in its own logs and invisible to the passenger. The fix is the listen address (and then the security group — [note 04](./04-infrastructure-and-network-security.md)), not a rewrite of the request handler.

---

## 6) End-to-end: naming the target

```
Passenger phone
  already has an IP (DHCP hands it out — note 02)
        │
        ▼
DNS: api.ridenow.example  --TTL cache-->  203.0.113.10
        │
        ▼
Destination socket:  203.0.113.10 : 443
Source socket:       192.168.1.42 : 51432   (ephemeral)
        │
        ▼
The packet now has a machine AND a service.
Delivery across networks is the next note.
```

One risk at each step:

- **Address:** the phone moved from Wi-Fi to cellular mid-session; the old source address is gone and existing connections die.
- **DNS:** a cached record still points at a drained server.
- **Port:** the process listens on localhost, or a second process already owns 443.

---

## 7) Reliability, security, and ops

- **Treat DNS TTL as a failover knob.** Lower it *before* a migration, not during the outage. Publish the new address, wait out the old TTL, then change traffic.
- **Publish both A and AAAA only when both paths work.** A broken IPv6 address with a working IPv4 address still black-holes clients that prefer v6.
- **Do not put databases on public addresses.** Private addressing is the first boundary; firewalls and security groups are the enforcement ([note 04](./04-infrastructure-and-network-security.md)).
- **Alert on listen address and port, not only process liveness.** A container that is "running" while bound to localhost is a networking bug.
- **Observe:** resolver latency, NXDOMAIN rate, TTL remaining on the answer you actually got, and `ss` showing the bind address.

---

## 8) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ip addr` / `ifconfig` | Local IPv4, IPv6, and MAC on each interface. |
| `dig api.ridenow.example A` | IPv4 answer, TTL, and which server answered. |
| `dig api.ridenow.example AAAA` | IPv6 answer. |
| `dig +trace api.ridenow.example` | The walk from root to the authoritative server. |
| `ss -lntp` | Listening TCP sockets and the address they bound (Linux). |
| `ss -lunp` | Listening UDP sockets (DNS on 53, for example). |

---

## 9) Key takeaways

- An IP address is **where a device can be reached now**, not who it permanently is.
- **IPv4 is 32-bit; IPv6 is 128-bit.** Same job, different pool size.
- **Private** addresses stay inside a network. **Public** addresses are how the internet reaches RideNow's front door.
- **DNS** turns a hostname into addresses, and **TTL** decides how long a wrong answer lingers.
- **Ports** pick the service. A live process bound to `127.0.0.1` is still unreachable from the network.

---

## 10) Quick glossary

- **IP address:** Logical location of an interface on an IP network.
- **Private address:** RFC 1918 (or IPv6 ULA) address, not routed on the public internet.
- **Public address:** Globally routable address.
- **DNS:** Domain Name System; hostname to address (and more).
- **TTL:** Seconds a cached DNS answer may be reused.
- **Port:** 16-bit selector for a service on a host.
- **Socket:** The pair of IP and port, plus the transport protocol.
- **Ephemeral port:** Short-lived source port chosen by the client.
- **Bind address:** The local address a server socket listens on.

---

## 11) Sources & further reading

- RFC 791 — *Internet Protocol (IPv4)*: <https://www.rfc-editor.org/rfc/rfc791>
- RFC 8200 — *Internet Protocol, Version 6 (IPv6)*: <https://www.rfc-editor.org/rfc/rfc8200>
- RFC 1918 — *Address Allocation for Private Internets*: <https://www.rfc-editor.org/rfc/rfc1918>
- RFC 6598 — *Shared address space (CGNAT)*: <https://www.rfc-editor.org/rfc/rfc6598>
- RFC 1035 — *Domain names, implementation and specification*: <https://www.rfc-editor.org/rfc/rfc1035>
- RFC 8305 — *Happy Eyeballs v2*: <https://www.rfc-editor.org/rfc/rfc8305>
- Cloudflare — *What is DNS?*: <https://www.cloudflare.com/learning/dns/what-is-dns/>
- Cloudflare — *What is IPv6?*: <https://www.cloudflare.com/learning/network-layer/what-is-ipv6/>
- Video chapters 01–03 (IP, DNS, ports): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
