# Bank Integration, Payment Gateways & E-Wallets — Detailed Notes

> Companion deep-dive for the summary diagram: `payment-gateways-bank-integration-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the *engineering* of a payment gateway: how it plugs into banks and card networks (including the legacy **ISO 8583** world), how it supports many **payment methods** (cards, net banking, e-wallets/PPI, UPI), how **tokenization/vaulting** works, and how **payment orchestration / smart routing** maximizes success rates.

---

## 1) What a payment gateway actually does

A gateway is the merchant-facing service that turns "customer wants to pay" into a bank-ready transaction. Core responsibilities:

1. **Capture** sensitive instrument data (card PAN, UPI VPA, wallet creds) via **hosted pages / iframes / SDKs** so raw data never touches the merchant server (PCI scope reduction — note 04).
2. **Tokenize + encrypt** the instrument and store a token in a **vault**.
3. **Route** the transaction to the right **processor / acquirer / network / bank rail** for the chosen method.
4. **Manage the lifecycle** (authorize, capture, refund, void) and expose it via REST APIs + **webhooks**.
5. **Reconcile & settle** — batch clearing, compute MDR, pay out to the merchant, produce settlement reports.

Indian gateways (Razorpay, PayU, CCAvenue, Paytm, Cashfree) and global ones (Stripe, Adyen, Braintree) all expose this same shape, differing mainly in **which rails** they natively support and **how much acquiring** they do themselves.

---

## 2) High-level gateway architecture

```
             ┌────────────────────── Payment Gateway / PSP ──────────────────────┐
 Merchant ─▶ │  API + Hosted Checkout / SDK                                       │
  app/web    │        │                                                           │
             │        ▼                                                           │
             │  [ Tokenization + Vault ]  [ Fraud/Risk engine ]  [ Orchestrator ] │
             │        │                          │                    │           │
             │        ▼                          ▼                    ▼           │
             │  [ Method adapters ]  cards | netbanking | wallet | UPI            │
             │        │        │          │          │                           │
             │        ▼        ▼          ▼          ▼                           │
             │  [ ISO 8583 ]  [ bank APIs / net-banking ]  [ NPCI UPI switch ]    │
             │  [ Ledger / Reconciliation / Settlement engine ]                   │
             │  [ Webhook / Notification service ]                                │
             └────────────────────────────────────────────────────────────────────┘
                        │                    │                     │
                        ▼                    ▼                     ▼
                  Card networks         Issuing/                NPCI /
                  (Visa/MC/RuPay)       acquiring banks         banks
```

Most large PSPs are **microservice** architectures (Razorpay is public about this): separate services for payments, orders, refunds, settlements, notifications, ledger — with **eventual consistency** handled by the **transactional outbox** pattern (note 03).

---

## 3) Bank & network integration — two protocol worlds

### 3a) The legacy core: ISO 8583
Card authorization/clearing between processors, acquirers, networks, and issuers historically runs on **ISO 8583** — a compact, bitmap-based binary message format. Key fields (data elements, "DE"):

| Field | Meaning |
| --- | --- |
| **MTI** | Message Type Indicator (e.g. `0100` auth request, `0110` auth response, `0200` financial request, `0400` reversal) |
| **DE2** | PAN (card number) |
| **DE3** | Processing code |
| **DE4** | Amount |
| **DE11** | **STAN** (System Trace Audit Number) — per-transaction trace for dedup/matching |
| **DE39** | Response code (`00` approved, `05` do not honor, `51` insufficient funds) |
| **DE41/42** | Terminal / merchant ID |

STAN + RRN (Retrieval Reference Number) are how the network **matches** auth ↔ reversal ↔ clearing and detects duplicates — the ISO-8583 equivalent of an idempotency key.

### 3b) The modern edge: REST + JSON
Merchant ↔ gateway is REST/JSON over HTTPS. **UPI** (note 05) is also REST/JSON/XML between PSP apps and NPCI. So real stacks contain a **translation layer**: JSON ⇄ ISO 8583, mapping API fields to data elements, doing validation/enrichment, PIN-block/MAC operations via **HSM**, and routing to the core banking system (CBS) or switch.

```
Merchant JSON ─▶ Gateway ─▶ [translate] ─▶ ISO 8583 ─▶ Acquirer switch ─▶ Network ─▶ Issuer CBS
                                        ◀── ISO 8583 response ── ◀── ── ◀── ──
```

### 3c) HSM (Hardware Security Module)
Dedicated tamper-resistant hardware that holds keys and performs crypto: **PIN block** encryption/translation, **MAC** generation/verification, card cryptogram validation, and key management. Required for handling PINs and network cryptograms; a compliance cornerstone.

---

## 4) Payment methods — the adapters

A gateway is really a fan-out over many **rails**, each with its own integration:

| Method | Rail / integration | Notes |
| --- | --- | --- |
| **Credit / debit cards** | Acquirer → network (ISO 8583) | Needs 3DS for CNP; tokenization; network tokens (VTS/MDES) |
| **Net banking** | Direct bank redirect / API per bank | Customer authenticates on their bank's page; async confirmation via callback/webhook; India: 50+ banks |
| **E-wallets / PPI** | Wallet provider API (Paytm, PhonePe, Amazon Pay, Mobikwik) | Prepaid balance; RBI-regulated **Prepaid Payment Instruments** |
| **UPI** | NPCI switch via PSP/sponsor bank | Collect & intent flows; QR; AutoPay mandates (note 05) |
| **EMI / BNPL / pay-later** | Lender APIs + card EMI | Credit underwriting; often orchestrated as a "linked payment" |
| **Bank transfer / virtual accounts** | IMPS/NEFT/RTGS + VA mapping | Reconciled by unique virtual account number |

**Net banking flow (async):** create order → redirect to bank → user logs in & authorizes → bank redirects back **and** sends a server-to-server callback → gateway confirms → webhook to merchant. As always, trust the **server-side status**, not the browser redirect.

---

## 5) E-wallets & Prepaid Payment Instruments (PPI)

An **e-wallet** stores a **prepaid balance** the user tops up from a card/bank/UPI. In India these are **PPIs** regulated by RBI, issued by banks or licensed non-banks.

- **Load / top-up:** money in → wallet balance (a **liability** the issuer owes the user; held in an **escrow/nodal account**).
- **Spend:** wallet debits balance and pays the merchant (often via the wallet provider's own settlement, sometimes over UPI rails).
- **Interoperability:** RBI mandated **full-KYC PPIs to be interoperable via UPI**, so a wallet can behave like a UPI PSP (note 05). This blurred the line between "wallet" and "UPI app" (Paytm, PhonePe, Amazon Pay).
- **Engineering concerns:** a wallet is a **ledger** — every load/spend/refund is a double-entry posting; balance must never go negative; reconciliation against the escrow account is mandatory.

---

## 6) Tokenization & the vault (payments-instrument side)

Two distinct kinds of tokens — don't conflate them (security detail in note 04):

- **Gateway/PSP vault token** — the gateway stores the card and gives the merchant an opaque token (e.g. Stripe `pm_...`, Razorpay token id). The merchant charges the token later without ever holding the PAN → **PCI scope shrinks**.
- **Network token** — issued by **Visa Token Service (VTS)** / **Mastercard Digital Enablement Service (MDES)**; a card-network-level replacement PAN bound to a merchant/device. Auto-updates when the card is reissued (fewer declines) and lifts authorization rates. In India, **RBI's Card-on-File Tokenization (CoFT)** mandate (from 2022) *requires* saved cards to be network-tokenized — merchants and gateways may **not** store raw PANs.

This is why "save my card" on Indian sites now silently creates a **network token**, not a stored card number.

---

## 7) Payment orchestration & smart routing

At scale, PSPs (and merchant orchestration layers) route each transaction to the **best acquirer/rail** to maximize **authorization success rate** and minimize cost:

- **Smart routing:** pick acquirer by BIN, issuer, amount, method, historical success, or cost.
- **Retry / fallback:** on a soft decline or acquirer outage, **retry via a different acquirer** (with the *same* idempotency intent — note 03) instead of failing the customer.
- **Linked / split payments:** combine methods (gift card + card + loyalty) into one order via a **payment orchestrator** running a state machine with **exactly-once** semantics — Razorpay's "LinkedPayments" is a public example: the orchestrator sequences each method, handles reversals if a later leg fails, and **withholds the "authorized" webhook until all legs authorize**.
- **Marketplace split / route settlement:** send parts of a payment to multiple sub-merchants (Razorpay Route, Stripe Connect).

**Observability of routing** = auth-rate per acquirer/BIN, cost per transaction, fallback trigger rate. A drop for one acquirer/BIN is a routing signal, not necessarily a bug.

---

## 8) Reliability / security / ops lens

- **Reliability:** rail adapters are independent failure domains → circuit-break a failing acquirer and route around it; make every leg idempotent; use the **outbox** for cross-service consistency (note 03).
- **Security:** hosted fields keep PAN out of merchant scope; HSM protects PINs/keys; network tokenization replaces stored PANs; TLS everywhere; secrets in a KMS (note 04).
- **Ops:** per-method dashboards (auth rate, latency, decline mix), settlement report generation, escrow/nodal reconciliation for wallets, and BIN/issuer health monitoring.

---

## 9) Key takeaways

- A gateway = **secure intake + tokenization + method adapters + lifecycle APIs + settlement/reconciliation**, usually as microservices.
- Real stacks bridge two worlds: **modern REST/JSON** at the edge and **legacy ISO 8583** (STAN/MTI/DE39) into banks, via a translation layer + **HSM**.
- Support many **rails**: cards, net banking, **e-wallets/PPI**, UPI, EMI/BNPL — each an adapter with its own confirmation model (mostly async → trust webhooks).
- **Tokenization** comes in two flavors: PSP-vault tokens (PCI scope) and **network tokens** (auth uplift); India's **CoFT** forbids storing raw PANs.
- **Payment orchestration** (smart routing, retries/fallback, linked/split payments) is how PSPs push authorization rates up and costs down.

---

## 10) Quick glossary

- **ISO 8583:** bitmap-based card messaging format (MTI, data elements, STAN, DE39).
- **STAN / RRN:** trace numbers used to match/dedup auth ↔ reversal ↔ clearing.
- **HSM:** hardware security module for PIN/key/crypto operations.
- **PPI:** Prepaid Payment Instrument (RBI-regulated e-wallet).
- **Escrow / nodal account:** bank account holding customer/wallet funds in trust.
- **Vault token:** PSP-issued opaque reference to a stored instrument.
- **Network token (VTS/MDES):** scheme-issued PAN replacement, merchant/device-bound.
- **CoFT:** RBI Card-on-File Tokenization mandate (no raw PAN storage).
- **Smart routing / orchestration:** choosing/retrying acquirers & rails to maximize success.

---

## 11) Sources & further reading

**Gateway architecture & microservices**
- Razorpay Engineering — *Atomic dual writes via Outboxer* (microservices + outbox): <https://engineering.razorpay.com/achieving-reliable-dual-writes-in-distributed-systems-cb9ff3b9bfc1>
- Razorpay Engineering — *LinkedPayments: payment chains in microservices*: <https://dev.to/razorpaytech/linkedpayments-building-payment-chains-in-a-microservices-architecture-43ca>
- Arpit Bhayani — *Razorpay's journey to microservices*: <https://arpit.substack.com/p/razorpays-journey-to-microservices>

**ISO 8583 / bank connectivity**
- Wikipedia — *ISO 8583*: <https://en.wikipedia.org/wiki/ISO_8583>
- V. Sharma — *ISO 8583 vs REST vs UPI: architecting multi-network payment systems*: <https://mvineetsharma.medium.com/iso-8583-vs-rest-apis-vs-upi-architecting-multi-network-payment-systems-in-net-10-2e8708034f9d>

**Tokenization / network tokens / CoFT**
- Visa — *Visa Token Service (VTS)*: <https://developer.visa.com/capabilities/vts>
- Mastercard — *Digital Enablement Service (MDES)*: <https://developer.mastercard.com/product/mdes-digital-enablement>
- RBI — *Tokenisation – Card Transactions (CoFT) FAQs*: <https://www.rbi.org.in/Scripts/FAQView.aspx?Id=161>

**Methods, wallets & PPI**
- RBI — *Master Directions on Prepaid Payment Instruments (PPIs)*: <https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12156>
- Razorpay — *Payment methods* docs: <https://razorpay.com/docs/payments/payment-methods/>
- PayU India — *Developer docs / payment methods*: <https://docs.payu.in/>
