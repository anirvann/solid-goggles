# Layer 2 — Data Link — Detailed Notes

> Companion deep-dive for the summary diagram: `data-link-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand how frames move between devices on the same local network using MAC addresses, how switches learn where to send them, and how ARP connects layer-3 IP addresses to layer-2 MAC addresses.

---

## 1) Big picture

Layer 2 delivers **frames** between **directly connected nodes on one link or LAN**. It does not know about the internet. It answers: *which network interface on this local segment should receive these bits?*

Responsibilities:

- **Framing:** marking where a unit of data starts and ends.
- **Physical addressing:** source and destination **MAC addresses**.
- **Error detection:** a **FCS** (CRC) trailer; corrupted frames are dropped.
- **Media access:** who may transmit on a shared medium (CSMA/CA on Wi-Fi).

**PDU:** frame.

IEEE splits layer 2 into two sublayers: **LLC** (logical link control, talks to layer 3) and **MAC** (media access control, talks to layer 1).

---

## 2) Components

### MAC address

- 48 bits, written `3c:22:fb:a1:09:c4`.
- First 24 bits: **OUI** (vendor). Last 24: device-specific.
- Assigned to a **network interface**, not a host. A laptop with Wi-Fi and Ethernet has two.
- Scope is **the local link only**. Routers replace MAC addresses at every hop.
- `ff:ff:ff:ff:ff:ff` is **broadcast** — every device on the segment receives it.
- Modern phones randomize their Wi-Fi MAC per network for privacy.

### IP vs MAC

| | IP address (L3) | MAC address (L2) |
| --- | --- | --- |
| Scope | End to end, across networks | One link / LAN segment |
| Changes along the path | No (except NAT) | **Yes, every hop** |
| Assigned by | DHCP, SLAAC, or static config | Manufacturer (or randomized) |
| Used by | Routers | Switches and NICs |

### Ethernet frame

```
| Preamble | Dst MAC | Src MAC | EtherType | Payload (46–1500 B) | FCS |
     8 B       6 B       6 B        2 B                               4 B
```

- **EtherType** tells the receiver what's inside (`0x0800` IPv4, `0x86DD` IPv6, `0x0806` ARP).
- **MTU** — maximum payload — is 1500 bytes by default; jumbo frames go to ~9000.
- **FCS** is a CRC over the frame; a mismatch means drop.

### Switch

A switch forwards frames by MAC address:

1. **Learn:** record the source MAC and the port it arrived on in the **MAC address table** (CAM table).
2. **Forward:** if the destination MAC is known, send out that port only.
3. **Flood:** if unknown, or broadcast, send out every port except the one it came in on.
4. **Age out:** forget entries after a timeout (often 300 s).

Each switch port is its own **collision domain**; the whole VLAN is one **broadcast domain**.

### ARP (Address Resolution Protocol, IPv4)

A host knows the destination IP (or the gateway's IP) but needs a MAC to build the frame:

```
Host   → broadcast  "Who has 192.168.1.1? Tell 192.168.1.42"
Router → unicast    "192.168.1.1 is at 3c:22:fb:a1:09:c4"
Host caches the answer in its ARP table
```

- If the destination is **on the same subnet**, ARP for the destination itself.
- If it's **off-subnet**, ARP for the **default gateway** — the frame goes to the router, the IP packet still says the final destination.
- IPv6 does this with **Neighbor Discovery (NDP)** over ICMPv6, not ARP.

### VLANs (802.1Q)

- Split one physical switch into multiple logical layer-2 networks.
- A 4-byte **tag** with a 12-bit VLAN ID is inserted in the frame on **trunk** links.
- Traffic between VLANs must go through a router (layer 3).

### Other layer-2 pieces

- **Wi-Fi (802.11):** same MAC idea, shared medium, uses CSMA/CA and ACKs per frame.
- **STP (Spanning Tree Protocol):** blocks redundant switch links to prevent loops (a layer-2 loop causes a broadcast storm — there is no TTL in Ethernet).
- **Link aggregation (LACP):** bundle several physical links into one logical link.
- **Bridges / access points:** connect layer-2 segments (an AP bridges Wi-Fi to Ethernet).

---

## 3) End-to-end flow: sending to a host on another network

```
1. App wants to reach 198.51.100.10; host's IP is 192.168.1.42/24
2. Not in 192.168.1.0/24 → next hop is gateway 192.168.1.1
3. ARP cache miss → broadcast "Who has 192.168.1.1?"
4. Gateway replies with its MAC; cache it
5. Build frame: dst MAC = gateway, src MAC = host, EtherType = IPv4
   payload = IP packet with dst IP 198.51.100.10
6. Switch looks up the gateway's MAC → forwards out one port
7. Router receives frame, checks FCS, strips L2 header
8. Router builds a NEW frame for the next link (new src/dst MAC)
```

The **IP destination never changes**; the **MAC destination changes at every router**.

---

## 4) Reliability, security, and ops

**Failure modes:**

- **Stale ARP entry** (device replaced, VM migrated, IP reassigned) → frames go to a MAC nobody owns until the entry expires. Fix: gratuitous ARP, flush the cache.
- **Switching loop** without STP → broadcast storm, network melts.
- **MTU mismatch** → large packets dropped, small ones work ("SSH works, file transfer hangs").
- **Wrong VLAN on a port** → device gets no DHCP lease or the wrong subnet.
- **MAC table overflow** → switch floods everything.

**Security:**

- **ARP spoofing / poisoning:** an attacker answers ARP for the gateway and becomes a man in the middle. Mitigations: Dynamic ARP Inspection, DHCP snooping, encryption above (TLS).
- **MAC flooding:** fill the CAM table so the switch floods traffic. Mitigation: port security.
- **VLAN hopping:** double tagging / switch spoofing. Mitigation: disable auto trunking, don't use the native VLAN for users.
- **802.1X:** authenticate a device before the port forwards its traffic.
- **MACsec (802.1AE):** encrypt frames hop by hop on wired links.

**What to monitor:** ARP table changes, CRC/FCS errors, STP topology changes, broadcast rates, MAC table size, interface drops.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ip link show` | Interface MAC address and MTU |
| `ip neigh` / `arp -a` | ARP / neighbor cache (`REACHABLE`, `STALE`, `FAILED`) |
| `sudo ip neigh flush dev eth0` | Clear stale entries |
| `arping -I eth0 192.168.1.1` | Send ARP requests directly |
| `bridge fdb show` | Linux bridge MAC table |
| `tcpdump -e -i eth0 arp` | Capture ARP with MAC headers |

---

## 6) Key takeaways

- Layer 2 moves **frames** between neighbors on **one link** using **MAC addresses**.
- **Switches learn** source MACs and forward by destination MAC; unknown destinations are flooded.
- **ARP** maps an IPv4 address to a MAC on the local network (IPv6 uses NDP).
- MAC addresses are **rewritten at every router hop**; IP addresses are not.
- VLANs create separate broadcast domains; crossing them needs layer 3.

---

## 7) Quick glossary

- **MAC address:** 48-bit identifier of a network interface.
- **Frame:** Layer-2 PDU with header, payload, and FCS.
- **FCS / CRC:** Checksum trailer used to detect corrupted frames.
- **MTU:** Largest payload a link will carry (default 1500 B on Ethernet).
- **CAM / MAC table:** Switch table mapping MACs to ports.
- **Broadcast domain:** Set of devices that receive each other's broadcasts.
- **ARP:** IPv4 protocol that resolves IP → MAC on the local link.
- **NDP:** IPv6 equivalent of ARP.
- **VLAN:** Logical layer-2 network on shared switches.
- **STP:** Protocol that prevents layer-2 loops.

---

## 8) Sources & further reading

- RFC 826 — *An Ethernet Address Resolution Protocol*: <https://www.rfc-editor.org/rfc/rfc826>
- RFC 4861 — *Neighbor Discovery for IPv6*: <https://www.rfc-editor.org/rfc/rfc4861>
- IEEE 802.3 — *Ethernet*: <https://standards.ieee.org/ieee/802.3/10422/>
- IEEE 802.1Q — *Bridges and bridged networks (VLANs)*: <https://standards.ieee.org/ieee/802.1Q/10323/>
- IEEE 802.1X — *Port-based network access control*: <https://standards.ieee.org/ieee/802.1X/7345/>
- Cloudflare — *What is ARP?*: <https://www.cloudflare.com/learning/network-layer/what-is-arp/>
