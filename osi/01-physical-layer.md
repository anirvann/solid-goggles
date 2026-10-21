# Layer 1 — Physical — Detailed Notes

> Companion deep-dive for the summary diagram: `physical-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand how bits become signals on copper, fiber, or radio, which hardware lives at layer 1, and which failures no amount of software retrying can fix.

---

## 1) Big picture

The physical layer moves **raw bits** between two directly connected devices. It does not know about frames, addresses, or applications. It defines:

- the **medium** (copper, fiber, radio),
- the **signal** (voltage levels, light pulses, radio modulation),
- **connectors and pinouts** (RJ45, LC/SC fiber, antennas),
- **timing and bit rate** (1 Gb/s, 10 Gb/s, Wi-Fi channel widths),
- **duplex** (half or full).

**PDU:** bit.

---

## 2) Components

### Media

| Medium | How bits travel | Typical reach | Strengths | Weaknesses |
| --- | --- | --- | --- | --- |
| Twisted-pair copper (Cat5e/6/6A) | Voltage changes | 100 m per Ethernet run | Cheap, PoE capable | Interference, distance limit |
| Coaxial | Voltage on a shielded core | Hundreds of meters (cable internet) | Shielded | Bulky |
| Multi-mode fiber | Light pulses (LED/VCSEL) | Hundreds of meters | High bandwidth, no EMI | Fragile, transceivers cost |
| Single-mode fiber | Laser light | Kilometers to 100+ km | Long haul, data center interconnects | Cost, precise optics |
| Radio (Wi-Fi, cellular) | Modulated electromagnetic waves | Meters (Wi-Fi) to kilometers (cellular) | Mobility | Shared medium, interference, walls |

### Hardware

| Device | Role at layer 1 |
| --- | --- |
| **NIC / PHY chip** | Converts frames from layer 2 into signals and back |
| **Transceiver (SFP/QSFP)** | Pluggable optics or copper module in a switch port |
| **Repeater** | Regenerates the signal to extend distance |
| **Hub** (legacy) | Repeats bits to every port — no addressing, one collision domain |
| **Cables, connectors, patch panels** | The literal medium |
| **Modem** | Modulates/demodulates between digital and the carrier (DSL, cable, fiber ONT) |

### Signal concepts

- **Encoding / line coding:** How bits map to signal changes (e.g. PAM4 on modern high-speed links, 8b/10b and 64b/66b to keep clocks synchronized).
- **Modulation:** How radio links carry bits (QAM in Wi-Fi and cellular; higher QAM = more bits per symbol, needs a cleaner signal).
- **Bandwidth vs throughput:** Bandwidth is the link's capacity; throughput is what you actually get after overhead, errors, and contention.
- **Attenuation:** Signal loss over distance.
- **Noise / interference:** Unwanted signal (other Wi-Fi networks, microwaves, unshielded cables next to power lines).
- **Duplex:** Full duplex sends and receives at once; half duplex takes turns. A **duplex mismatch** silently destroys throughput.

---

## 3) End-to-end flow: one frame on the wire

```
Layer 2 hands a frame to the NIC
        │
        ▼
PHY encodes bits (line coding) and adds a preamble for clock sync
        │
        ▼
Signal on the medium: voltage / light / radio
        │   attenuation, noise, interference
        ▼
Receiver PHY recovers the clock, decodes bits
        │
        ▼
Bits handed up to layer 2, which checks the FCS (CRC)
```

Layer 1 does **not** detect most errors itself. Corrupted bits show up one layer higher as **FCS / CRC errors** on frames.

---

## 4) Reliability, security, and ops

**Failure modes:**

- Unplugged or damaged cable → interface `NO-CARRIER` / link down.
- Dirty or bent fiber → rising CRC errors, flapping link.
- Wi-Fi interference or weak signal → low data rate, retransmissions at layer 2, high latency.
- Auto-negotiation or duplex mismatch → link "up" but terrible throughput and late collisions.
- Power loss on a switch or PoE budget exceeded → devices drop off.

**Reliability controls:**

- Redundant links and physically diverse paths (two fibers in the same trench fail together).
- Link aggregation (layer 2) over multiple physical links.
- UPS / dual power supplies.

**Security:**

- Physical access is total access: a port in a lobby can be a way onto the network (mitigated at layer 2 with 802.1X).
- Wireless signals leave the building — that is why Wi-Fi needs strong encryption (WPA3).
- Taps on copper or fiber are possible; encryption at higher layers (TLS, IPsec, MACsec) is the answer.

**What to monitor:** link state changes (flaps), CRC/FCS error counters, optical receive power, Wi-Fi RSSI and SNR, interface speed and duplex.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `ip link show` | Interface up/down and `NO-CARRIER` |
| `ethtool eth0` | Negotiated speed, duplex, link detected |
| `ethtool -S eth0` | Error counters (CRC, drops) |
| `iw dev wlan0 link` | Wi-Fi signal strength and bit rate |
| `ethtool -m eth0` | Optical transceiver diagnostics (Rx/Tx power) |

---

## 6) Key takeaways

- Layer 1 is **bits as signals**: medium, connector, encoding, timing.
- Choice of medium is a trade-off of **distance, bandwidth, cost, and interference**.
- Physical problems show up **one layer up** as CRC errors and flapping links.
- **No software retry fixes a broken cable.** Check link state first when everything is down.
- Wireless is a **shared, leaky medium** — encrypt above it.

---

## 7) Quick glossary

- **PHY:** The chip/circuit that implements layer 1 on a NIC or switch port.
- **Transceiver (SFP/QSFP):** Pluggable module that converts electrical signals to optical (or copper).
- **Attenuation:** Loss of signal strength over distance.
- **Modulation:** Encoding bits onto a carrier wave.
- **Duplex:** Whether a link sends and receives at the same time.
- **Hub:** Legacy device that repeats bits to all ports.
- **SNR:** Signal-to-noise ratio — higher is cleaner.

---

## 8) Sources & further reading

- IEEE 802.3 — *Ethernet* (physical layer specs): <https://standards.ieee.org/ieee/802.3/10422/>
- IEEE 802.11 — *Wireless LAN*: <https://standards.ieee.org/ieee/802.11/7028/>
- Cisco — *Ethernet technologies* overview: <https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/configuration/xe-16/ir-xe-16-book/ir-ethernet.html>
- Fiber Optic Association — *Fiber optic basics*: <https://www.thefoa.org/tech/ref/basic/fiber.html>
- Cloudflare — *What is the OSI model?*: <https://www.cloudflare.com/learning/ddos/glossary/open-systems-interconnection-model-osi/>
