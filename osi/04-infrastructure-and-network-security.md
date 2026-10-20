# Infrastructure & Network Security — Detailed Notes

> Companion deep-dive for the summary diagram: `infrastructure-security-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Narrative companion: [Cloud X Berry — Networking topics, one RideNow request](https://www.youtube.com/watch?v=TR0RU2pmMeA) (chapters 14–16, about 15:41–18:50).

**Learning goal:** Explain how a growing RideNow puts a load balancer and a reverse proxy in front of many services, and how firewalls make sure passengers can reach the front door without reaching the database.

Protocols are covered in [note 03](./03-transport-and-application-protocols.md). Subnets that give these boxes somewhere to live are in [note 02](./02-local-delivery-routing-nat.md).

---

## 1) Big picture

One app server is enough for a demo. It is not enough when thousands of passengers tap Request Ride at once, and it is the wrong place to terminate TLS, route to a dozen services, and also hold the database.

Three boxes show up, in this order of need:

| Piece | Problem it solves | What it does *not* do |
| --- | --- | --- |
| **Load balancer** | One server cannot take the traffic, and a dead server should not | Understand every URL, by itself |
| **Reverse proxy** | Clients should see one front door, not every internal service | Replace health checks or a firewall |
| **Firewall** | Not every reachable path should be allowed | Scale the application |

Their jobs overlap in real products. Nginx, Envoy, HAProxy, and cloud load balancers often do more than one of these. The useful distinction is the **job**, not the product name.

---

## 2) Load balancer

RideNow runs several copies of the API. The passenger's phone still calls one hostname. The **load balancer** accepts the connection and picks a **healthy** backend.

```
Passenger ──▶ load balancer ──▶ api-1  (healthy)
                            ├──▶ api-2  (healthy)
                            └──▶ api-3  (failed health check — no new requests)
```

What that buys:

- **Scale.** Add instances when request rate or CPU grows. The phone's DNS name does not change.
- **Availability.** A failed instance is removed from rotation. The others keep accepting rides.
- **A single entry address.** Backends can move, scale, and die without republishing client configuration.

Health is an active check (`GET /health` every few seconds), a passive signal (error rate, timeouts), or both. "Healthy" has to mean "can take a ride request," not only "the process is running." An instance that passes `/health` while its driver-service dependency is down will still burn passenger requests.

Related knobs:

- **Connection draining.** On deploy, stop sending new work and let in-flight requests and WebSockets finish or migrate.
- **Algorithm.** Round robin is a fine default. Least-connections helps when some requests (a dispatch call) are much slower than others.
- **Stickiness.** Needed only when one instance holds state for a connection (a WebSocket that is not backed by a shared bus). Prefer shared state, and keep the balancer free to choose any healthy instance.

---

## 3) Reverse proxy

A **reverse proxy** sits between clients and backend services and acts as the intermediary. The passenger never learns whether a URL is served by the passenger service, the driver service, or the trip service.

For RideNow the proxy can:

| Job | Why it lives here |
| --- | --- |
| **Route** | `/v1/rides` → trip service, `/v1/drivers` → driver service |
| **Terminate TLS** | One certificate at the edge; services can speak HTTP or re-encrypted HTTPS inside |
| **Cache** | Repeated, safe responses (a static config document, a map tile) never hit the app |
| **Compress** | One place to gzip or Brotli, instead of every service |
| **Hide topology** | Internal hostnames and ports stay off the public internet |

"Reverse" means the proxy stands in front of servers, on the client's behalf toward the origin. A **forward** proxy is the opposite direction: an internal client going out through a shared egress. RideNow's passenger-facing box is a reverse proxy.

TLS termination here matches [note 03](./03-transport-and-application-protocols.md): the passenger's HTTPS session ends at the proxy. If the hop from proxy to trip service crosses a network you do not fully trust, encrypt that hop again. Inside a single locked-down subnet, teams sometimes run plaintext; that is an explicit trade, not the default to copy onto a public subnet.

---

## 4) Where the load balancer and the reverse proxy overlap

A single process can balance *and* proxy. Cloud "application load balancers" route on the URL and check health. A proxy can have an upstream pool of three trip-service pods.

Keep the two questions separate even when one box answers both:

1. **Which pool, and which healthy member?** That is balancing.
2. **What should happen to this HTTP request at the front door** — TLS, route, cache, compress, add a request id? That is the reverse proxy.

Splitting them (proxy tier, then a balancer per service) is normal once teams deploy independently. Combining them is normal at the start. The failure mode to avoid is assuming "we have a load balancer" means "TLS, routing, and access control are handled."

---

## 5) Firewalls

A path to a service is not permission to use it. A **firewall** allows some flows and blocks the rest.

RideNow's minimum policy:

| From | To | Decision |
| --- | --- | --- |
| Public internet | Edge proxy, TCP 443 | Allow |
| Public internet | Database, TCP 5432 | **Block** |
| Application subnet | Database, TCP 5432 | Allow |
| Application subnet | Anything else on the data subnet | Block |
| Edge | Application ports | Allow |
| Application | Edge's admin port | Block |

In a cloud VPC those rules are often **security groups** or network ACLs. In Kubernetes they are **NetworkPolicies**. The mechanism changes; the question does not: which source may open which port on which destination?

Debugging consequence, and the one the video is built around: the database is up, the password is right, and the app still times out. A rule between the two subnets is **dropping** the SYN. Nothing in the application log will say so, because the packet never arrived. A reject (TCP RST, or ICMP unreachable) fails fast. A drop fails as a timeout. When you see a timeout, include the firewall on the checklist before you rewrite the client.

NAT ([note 02](./02-local-delivery-routing-nat.md)) is not this control. NAT lets private hosts open outbound flows. A firewall is the allow/deny list.

---

## 6) End-to-end: the ride request inside RideNow

```
Passenger phone
    │  TCP 443, TLS
    ▼
[firewall]  allow internet → :443 only
    ▼
[reverse proxy]  terminate TLS, route POST /v1/rides → trip pool
    ▼
[load balancer]  pick a healthy trip-service instance
    ▼
[trip service]  validate rider, write the trip, call dispatch
    │
    ▼
[firewall]  allow app subnet → database :5432; block the internet
    ▼
[database]
    │
    ▼
HTTP 201 back up the same path
```

Later, the WebSocket for driver location uses the same front door. The proxy must be willing to upgrade and to hold the socket ([note 03](./03-transport-and-application-protocols.md)).

One risk per hop:

- **Firewall:** a new port not added to the security group → timeout.
- **Proxy:** a route sending `/v1/rides` to the driver service → confusing 404s.
- **Balancer:** health check too shallow → traffic to a broken instance.
- **App to database:** a policy that allows the app subnet but the pod IP is in a different subnet → timeout again.

---

## 7) Reliability, security, and ops

- **Health checks hit a real dependency path**, or at least fail when the process cannot do work. A check that always returns 200 keeps a dead instance in rotation.
- **Drain before killing.** Ride requests in flight, and location WebSockets, need a stop-accepting window.
- **The front door is a blast radius.** Two proxies in two zones beat one heroic box. The balancer's own failure is why DNS or anycast often points at more than one of them.
- **Least privilege on paths.** Internet to 443 on the edge. App to the database port. Nothing else inbound to the data subnet.
- **Log the refusal.** Dropped packets are invisible unless the firewall or security group emits a reject/drop log. Turn that on before the next timeout.
- **Do not cache personalized ride responses.** Cache only responses that are safe to share. A cached `GET /v1/trips/mine` is a data leak.
- **TLS at the edge, and a story for the hop behind it.** Know which network segment is inside the trust boundary.

---

## 8) Hands-on checks

| Check | What it tells you |
| --- | --- |
| Security group / NetworkPolicy review | Is 5432 open to the app subnet and closed to `0.0.0.0/0`? |
| Target health in the load balancer | Which instances were pulled, and why. |
| Proxy access log | Did the request arrive, what upstream was chosen, what status came back. |
| `curl -v` from a client vs. from inside the app subnet | Splits "firewall in front" from "app bug". |
| Firewall drop logs during a timeout | Confirms a silent discard. |

---

## 9) Key takeaways

- A **load balancer** spreads requests across healthy servers so RideNow can scale and lose an instance without losing the product.
- A **reverse proxy** is the front door: route, terminate TLS, cache, compress, and hide internal services.
- Real components often do both. Name the **job** you need so "we have a load balancer" does not silently skip TLS or access control.
- **Firewalls** allow the passenger to reach the edge and allow the app to reach the database, and they block the internet from the database.
- A **timeout with a healthy process** is often a dropped packet on a security boundary.

---

## 10) Quick glossary

- **Load balancer:** Distributes traffic across a pool and skips unhealthy members.
- **Health check:** Probe that decides whether a member stays in the pool.
- **Reverse proxy:** Server-side intermediary that receives the client request and forwards it inward.
- **TLS termination:** The proxy decrypts HTTPS and speaks to the service behind it on a new connection.
- **Firewall:** Policy that allows or blocks flows, usually by source, destination, protocol, and port.
- **Security group:** Cloud firewall attached to an interface or instance.
- **NetworkPolicy:** Kubernetes rules for which pods may connect to which pods.
- **Draining:** Refusing new work while existing work finishes.

---

## 11) Sources & further reading

- RFC 9110 — *HTTP semantics* (proxy and gateway roles): <https://www.rfc-editor.org/rfc/rfc9110>
- RFC 8446 — *TLS 1.3* (what termination is actually speaking): <https://www.rfc-editor.org/rfc/rfc8446>
- AWS — *Security group basics* and connection tracking: <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html>
- AWS — *How Elastic Load Balancing works*: <https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/how-elastic-load-balancing-works.html>
- Kubernetes — *Network Policies*: <https://kubernetes.io/docs/concepts/services-networking/network-policies/>
- NGINX — *Reverse proxy* basics: <https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/>
- Envoy — *Overview* (proxy, routing, load balancing): <https://www.envoyproxy.io/docs/envoy/latest/intro/what_is_envoy>
- Video chapters 14–16 (load balancer, reverse proxy, firewall): <https://www.youtube.com/watch?v=TR0RU2pmMeA>
