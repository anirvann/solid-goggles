# Layer 5 — Session — Detailed Notes

> Companion deep-dive for the summary diagram: `session-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand what "session" means in networking — establishing, maintaining, resuming, and tearing down a conversation — and where those functions actually live in TCP/IP systems (keep-alive, TLS resumption, WebSocket heartbeats, RPC sessions, auth sessions).

---

## 1) Big picture

The session layer manages the **dialog** between two applications: who is talking, whether the conversation is still alive, and how to pick it back up after an interruption.

OSI defines these functions:

- **Establishment, maintenance, and release** of a session.
- **Dialog control:** full duplex or half duplex (take turns).
- **Synchronization / checkpoints:** resume a long transfer from the last checkpoint instead of from zero.

TCP/IP has **no dedicated session-layer protocol**. The functions are real, but they live in TCP, TLS, HTTP, WebSocket, RPC frameworks, and the application. Treat layer 5 as a question — *"Is there a conversation, and is it still up?"* — rather than a box with one protocol in it.

**PDU:** data (no distinct header in TCP/IP).

---

## 2) Components (where layer-5 functions live in practice)

| Function | Concrete mechanism |
| --- | --- |
| Establish a session | TLS handshake, WebSocket upgrade, SSH session, RPC channel setup, login |
| Keep it alive | TCP keepalive, HTTP keep-alive, WebSocket ping/pong, gRPC keepalive, app heartbeats |
| Reuse it | HTTP persistent connections, connection pools, HTTP/2 multiplexing |
| Resume it | TLS session tickets / PSK, QUIC 0-RTT, resumable uploads |
| Checkpoint | Byte-range requests (`Range:` header), resumable upload protocols, DB transaction savepoints |
| End it | TCP FIN, TLS `close_notify`, WebSocket close frame, logout / token expiry |
| Identify it | Session ID cookie, bearer token, TLS session ID, QUIC connection ID |

### Persistent connections and connection pools

- **HTTP/1.1 keep-alive:** reuse one TCP+TLS connection for many requests instead of paying handshakes each time.
- **HTTP/2:** many concurrent request **streams** multiplexed over one connection.
- **Connection pools** (DB drivers, HTTP clients): a set of warm connections handed out per request.

### Long-lived sessions: WebSockets

- Start as an HTTP request with `Upgrade: websocket`, server replies `101 Switching Protocols`.
- Then one TCP connection stays open, **full duplex**: the server can push without being asked.
- Kept alive with **ping/pong** frames; ended with a close frame.
- Protocol details in [`07-application-layer.md`](./07-application-layer.md).

### Session resumption

- **TLS 1.3 resumption:** after a full handshake, the server issues a ticket; next time the client presents it and skips certificate exchange.
- **0-RTT (early data):** client sends data in the very first flight. Fast, but **replayable** — only for idempotent requests.
- **QUIC connection IDs:** the session survives an IP change (Wi-Fi → cellular).

### Application sessions

- Login creates a **server-side session** (ID in a cookie) or a **token** (JWT, OAuth access token).
- Not a network session, but the same layer-5 idea: identity and state across many requests over many connections.

### Classic OSI-era examples

- **NetBIOS session service**, **RPC** (Sun RPC, DCE/RPC), **SQL*Net**, **PPTP control**, **SIP** dialog management. Mostly historical or niche, but they show the intended role.

---

## 3) End-to-end flow: a session's life

```
1. Establish   TCP handshake → TLS handshake → (login) → session ID / token
2. Use         many HTTP requests over the same connection (keep-alive / HTTP/2)
3. Maintain    idle → heartbeat (TCP keepalive, WS ping) so NAT/LB don't drop it
4. Interrupt   network change or idle timeout kills the connection
5. Resume      new TCP connection + TLS resumption ticket; same app token
6. Release     WebSocket close / TLS close_notify / TCP FIN; token expires
```

---

## 4) Reliability, security, and ops

**Failure modes:**

- **Idle timeouts** on load balancers (often 60 s), NAT gateways, or firewalls silently kill quiet sessions. Symptom: first request after a pause fails. Fix: heartbeats shorter than the shortest idle timeout, client retry on reconnect.
- **Sticky-session dependency:** state kept in one server's memory → users lose it when that server dies or deploys. Prefer shared session stores (Redis) or stateless tokens.
- **Deploys drop long-lived connections** → need draining and client reconnect with backoff (avoid a thundering herd).
- **Connection pool exhaustion** → requests queue waiting for a free connection.
- **Stale pooled connections** → server closed it, client tries to reuse it. Validate or set max lifetime.

**Security:**

- **Session hijacking:** stealing a session cookie/token. Mitigations: TLS everywhere, `Secure` + `HttpOnly` + `SameSite` cookies, short lifetimes, rotation on login.
- **Session fixation:** attacker sets the victim's session ID. Mitigation: issue a new ID after authentication.
- **0-RTT replay:** never accept non-idempotent actions in early data.
- **Absolute and idle expiry** for auth sessions; revoke on logout.

**What to monitor:** active connections / sessions, reconnect rate, idle-timeout disconnects, pool wait time and saturation, TLS resumption rate, WebSocket close codes.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `curl -v --http1.1 https://a https://b` | Whether curl reuses the connection ("Re-using existing connection") |
| `openssl s_client -connect host:443 -sess_out s.pem` then `-sess_in s.pem` | TLS session resumption ("Reused") |
| `ss -tno` | Connections with keepalive timers |
| `sysctl net.ipv4.tcp_keepalive_time` | OS TCP keepalive interval |
| Browser devtools → Network → WS | WebSocket frames, ping/pong, close codes |

---

## 6) Key takeaways

- Layer 5 is about the **conversation**: establish, maintain, resume, release.
- TCP/IP has **no separate session protocol** — the functions live in TCP, TLS, HTTP, WebSockets, RPC frameworks, and apps.
- **Reuse** sessions (keep-alive, pools, HTTP/2) to avoid repeated handshakes.
- **Heartbeats** must beat the shortest idle timeout on the path (NAT, LB, firewall).
- Protect **session identifiers** like passwords; 0-RTT data is replayable.

---

## 7) Quick glossary

- **Session:** A logical conversation spanning one or more connections or requests.
- **Keep-alive:** Reusing a connection, or sending probes to keep it open.
- **Heartbeat / ping-pong:** Periodic small messages proving the peer is alive.
- **Connection pool:** Reusable set of open connections.
- **Session resumption:** Re-establishing a secure session with a shortcut.
- **0-RTT:** Sending data in the first flight of a resumed connection.
- **Sticky session:** Load balancer pins a client to one backend.
- **Session ID / token:** Identifier linking requests to a session.

---

## 8) Sources & further reading

- ITU-T X.215 / X.225 — *OSI session service and protocol*: <https://www.itu.int/rec/T-REC-X.215/en>
- RFC 9112 — *HTTP/1.1* (persistent connections): <https://www.rfc-editor.org/rfc/rfc9112#name-persistence>
- RFC 9113 — *HTTP/2* (stream multiplexing): <https://www.rfc-editor.org/rfc/rfc9113>
- RFC 8446 — *TLS 1.3* §2.2 resumption and 0-RTT: <https://www.rfc-editor.org/rfc/rfc8446#section-2.2>
- RFC 6455 — *The WebSocket Protocol*: <https://www.rfc-editor.org/rfc/rfc6455>
- OWASP — *Session Management Cheat Sheet*: <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>
- AWS — *Elastic Load Balancing idle timeout*: <https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#connection-idle-timeout>
