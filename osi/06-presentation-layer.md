# Layer 6 — Presentation — Detailed Notes

> Companion deep-dive for the summary diagram: `presentation-layer-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.
>
> Overview of how all layers fit: [`00-osi-model-overview.md`](./00-osi-model-overview.md).

**Learning goal:** Understand how data is represented so both sides interpret it the same way — character encoding, serialization, compression — and how TLS (HTTPS) provides encryption, integrity, and authentication.

---

## 1) Big picture

The presentation layer is the **translator**. The application says *what* it wants to send; layer 6 decides *how the bytes look* on the wire so the other side can understand them.

OSI responsibilities:

- **Translation / encoding:** character sets, byte order, data formats.
- **Serialization:** turning in-memory structures into bytes.
- **Compression:** fewer bytes on the wire.
- **Encryption / decryption:** confidentiality and integrity.

In TCP/IP, these are done by libraries inside the application process (a JSON encoder, gzip, a TLS library). **TLS** is conventionally taught at layer 6 even though it runs over TCP and is usually described as sitting between transport and application.

---

## 2) Components

### Character encoding

| Encoding | Notes |
| --- | --- |
| ASCII | 7-bit, English only |
| UTF-8 | Variable 1–4 bytes, ASCII-compatible, the web default |
| UTF-16 | 2 or 4 bytes, used internally by Windows, Java, JavaScript |

Mismatch symptom: "mojibake" (`Ã©` instead of `é`). Fix: declare it (`Content-Type: application/json; charset=utf-8`) and use UTF-8 end to end.

**Byte order (endianness):** network protocols use **big-endian** ("network byte order"); most CPUs are little-endian. Libraries convert (`htons`, `ntohl`).

### Serialization formats

| Format | Type | Strengths | Trade-offs |
| --- | --- | --- | --- |
| JSON | Text | Human-readable, universal | Verbose, no schema by default |
| XML | Text | Schemas, namespaces | Very verbose |
| Protocol Buffers | Binary | Compact, fast, schema evolution | Needs `.proto` schema, not readable |
| Avro / Thrift / MessagePack / CBOR | Binary | Compact; Avro has schema registry patterns | Tooling varies |
| ASN.1 (DER/BER) | Binary | Used by X.509 certificates, SNMP, LDAP | Complex |

**Base64** encodes binary as text (for JSON, email, URLs) at ~33 % size overhead.

Media types are presentation too: JPEG, PNG, WebP, MP4, Opus. HTTP negotiates them with `Accept` / `Content-Type`.

### Compression

| Algorithm | Where you see it |
| --- | --- |
| gzip / DEFLATE | HTTP `Content-Encoding: gzip`, the classic default |
| Brotli (`br`) | Better ratio for text on the web |
| Zstandard (`zstd`) | Fast, good ratio; logs, storage, newer HTTP |
| HPACK / QPACK | Header compression in HTTP/2 / HTTP/3 |

Negotiated via `Accept-Encoding` → `Content-Encoding`. Don't compress already-compressed media (JPEG, MP4). Compressing secrets alongside attacker-controlled input can leak data (CRIME/BREACH).

### TLS — encryption, integrity, authentication

**HTTPS = HTTP over TLS.** TLS provides:

1. **Confidentiality** — eavesdroppers can't read the data (symmetric encryption, e.g. AES-GCM, ChaCha20-Poly1305).
2. **Integrity** — tampering is detected (AEAD tags).
3. **Authentication** — the client verifies the server's identity with a certificate (and optionally the server verifies the client: **mTLS**).

**TLS 1.3 handshake (simplified, 1-RTT):**

```
Client ── ClientHello (versions, cipher suites, key share, SNI) ─────▶ Server
Client ◀─ ServerHello (chosen suite, key share)
          {EncryptedExtensions, Certificate, CertificateVerify, Finished} ─ Server
Client ── {Finished} ─────────────────────────────────────────────▶ Server
          application data, encrypted both ways
```

- Key exchange is **ephemeral (EC)DHE** → **forward secrecy**: a later private-key leak doesn't decrypt past traffic.
- **TLS 1.2** needs 2 RTTs; **TLS 1.3** needs 1, and resumption can do **0-RTT** (replayable — idempotent requests only).
- **SNI** tells the server which hostname is wanted (one IP, many certificates). **ECH** encrypts it.
- **ALPN** negotiates the application protocol (`h2`, `http/1.1`) inside the handshake.

**Certificates and the chain of trust:**

1. Server presents an **X.509 certificate**: its public key + names (SAN) + validity + issuer signature.
2. Signed by an **intermediate CA**, which is signed by a **root CA**.
3. The OS/browser ships a set of trusted roots.
4. Client checks: chain to a trusted root, hostname matches SAN, not expired, not revoked (OCSP/CRL), signature valid.
5. Certificate is proved by the server signing the handshake with the matching **private key**.

**Asymmetric vs symmetric:** asymmetric crypto (RSA/ECDSA signatures, ECDHE key exchange) is used in the handshake; bulk data uses fast **symmetric** keys derived from it.

**TLS termination:** a load balancer or reverse proxy often decrypts TLS, inspects/routes HTTP, then re-encrypts to the backend (or not, inside a trusted segment). See [`08-devices-and-security-across-layers.md`](./08-devices-and-security-across-layers.md).

---

## 3) End-to-end flow: from object to wire

```
Sender
1. App object      {"city": "München", "temp": 7}
2. Serialize       JSON text
3. Encode          UTF-8 bytes  (ü → 0xC3 0xBC)
4. Compress        gzip / br     (Content-Encoding)
5. Encrypt         TLS record: AEAD(key, bytes) + tag
6. Hand to layer 4 (TCP)

Receiver reverses: decrypt + verify tag → decompress → decode UTF-8 → parse JSON
```

---

## 4) Reliability, security, and ops

**Failure modes:**

- **Expired certificate** → every client fails at once. The most common avoidable outage.
- **Hostname mismatch** (cert for `www.example.com`, request to `example.com`).
- **Incomplete chain** (server didn't send the intermediate) → works in some clients, fails in others.
- **Protocol/cipher mismatch** — old clients vs TLS 1.3-only servers.
- **Clock skew** → valid certs look "not yet valid" or expired.
- **Encoding mismatch** → garbled text, failed signature checks on re-encoded data.
- **Schema drift** (Protobuf/Avro field changes) → deserialization errors between versions.

**Security:**

- Use **TLS 1.2+**, prefer 1.3; disable SSLv3/TLS 1.0/1.1.
- **HSTS** to force HTTPS; redirect HTTP → HTTPS.
- **Automate certificates** (ACME / Let's Encrypt, or a managed CA) and alert well before expiry.
- **mTLS** for service-to-service authentication.
- Protect private keys (HSM/KMS); rotate.
- Don't trust deserialization of untrusted input in formats that instantiate arbitrary types (Java serialization, Python pickle).

**What to monitor:** certificate days-to-expiry, TLS handshake error rate, negotiated versions/ciphers, resumption rate, decompression/parse errors.

---

## 5) Hands-on commands

| Command | What it shows |
| --- | --- |
| `openssl s_client -connect example.com:443 -servername example.com` | Chain, negotiated version and cipher |
| `openssl x509 -in cert.pem -noout -text` | Certificate fields, SANs, dates |
| `echo \| openssl s_client -connect host:443 2>/dev/null \| openssl x509 -noout -dates` | Expiry dates |
| `curl -v https://example.com` | TLS handshake summary + HTTP |
| `curl -sI -H 'Accept-Encoding: br,gzip' https://example.com` | Which compression the server picked |
| `file -i data.txt` / `iconv` | Detect / convert character encoding |

---

## 6) Key takeaways

- Layer 6 is **representation**: encoding, serialization, compression, encryption.
- Agree on formats explicitly — **UTF-8**, declared content types, versioned schemas.
- **TLS** gives confidentiality, integrity, and authentication; TLS 1.3 is 1-RTT with forward secrecy.
- **Certificates** chain to a trusted root and must match the hostname and be in date.
- In TCP/IP these functions live **inside the app or proxy**, not in a separate protocol layer.

---

## 7) Quick glossary

- **Encoding:** Mapping characters to bytes (UTF-8).
- **Serialization:** Converting data structures to bytes (JSON, Protobuf).
- **Endianness:** Byte order of multi-byte numbers.
- **TLS:** Transport Layer Security.
- **AEAD:** Authenticated encryption — confidentiality and integrity together.
- **Forward secrecy:** Past sessions stay safe if a long-term key leaks.
- **X.509 certificate:** Signed binding of a public key to names.
- **CA:** Certificate authority that signs certificates.
- **SNI / ALPN:** TLS extensions for hostname and app-protocol negotiation.
- **mTLS:** Both sides present certificates.
- **HSTS:** Header telling browsers to only use HTTPS.

---

## 8) Sources & further reading

- RFC 8446 — *TLS 1.3*: <https://www.rfc-editor.org/rfc/rfc8446>
- RFC 5280 — *X.509 certificate and CRL profile*: <https://www.rfc-editor.org/rfc/rfc5280>
- RFC 3629 — *UTF-8*: <https://www.rfc-editor.org/rfc/rfc3629>
- RFC 8259 — *JSON*: <https://www.rfc-editor.org/rfc/rfc8259>
- RFC 9110 §8.4 — *Content-Encoding*: <https://www.rfc-editor.org/rfc/rfc9110#name-content-encoding>
- RFC 7932 — *Brotli*: <https://www.rfc-editor.org/rfc/rfc7932>
- Protocol Buffers documentation: <https://protobuf.dev/>
- Cloudflare — *What happens in a TLS handshake?*: <https://www.cloudflare.com/learning/ssl/what-happens-in-a-tls-handshake/>
- Let's Encrypt — *How it works*: <https://letsencrypt.org/how-it-works/>
- Mozilla — *Server Side TLS guidelines*: <https://wiki.mozilla.org/Security/Server_Side_TLS>
