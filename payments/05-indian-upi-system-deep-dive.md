# Indian UPI System — Deep Dive — Detailed Notes

> Companion deep-dive for the summary diagram: `upi-system-architecture-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand India's **Unified Payments Interface (UPI)** end to end — who NPCI/PSPs/banks are, how a **VPA** and **2-factor MPIN** work, the **pay vs collect** flows, how the **NPCI switch** talks to banks (and bridges to legacy **ISO 8583**), settlement, mandates/**AutoPay**, **UPI Lite**, **Credit Line on UPI**, and the **UDIR** dispute framework.

---

## 1) What UPI is (and why it's different)

**UPI** is a real-time, mobile-first, **interoperable** payment system built by **NPCI** (National Payments Corporation of India) under RBI guidance, launched **2016**. It lets any bank account send/receive money instantly via a phone, using a simple **Virtual Payment Address (VPA)** like `name@bank` instead of account numbers.

Why it's a landmark system:
- **Interoperable & open:** any UPI app can pay any bank account / any other app (unlike closed wallets).
- **Real-time, 24×7** bank-to-bank transfer, built on top of **IMPS** rails.
- **Single-click 2-factor auth:** the **MPIN** on a **device-bound** app satisfies two factors (something you have = phone/SIM, something you know = MPIN) — no separate OTP+PIN.
- **Near-zero cost (P2M MDR = 0 by regulation)** — a huge adoption driver.
- **API-first:** REST/JSON(/XML) between apps and NPCI, enabling rapid feature rollout (Lite, Circle, Credit Line, AutoPay).

Scale context: UPI processes **billions** of transactions per month and is the dominant retail payment rail in India.

---

## 2) The actors — the four-pillar model

UPI runs a **four-pillar, push–pull interoperable** model:

| Pillar | Who | Role |
| --- | --- | --- |
| **Remitter (payer) PSP** | The payer's UPI app (front-end) | Onboards user, creates VPA, captures MPIN, sends requests |
| **Remitter bank (issuer)** | Payer's bank | Debits the payer's account; validates MPIN via its switch |
| **Beneficiary (payee) PSP** | The payee's UPI app / merchant PSP | Receives/initiates collect; resolves payee VPA |
| **Beneficiary bank (acquirer)** | Payee's bank | Credits the payee's account |
| **NPCI (the switch)** | Central operator | Routes every request between PSPs and banks; validates; orchestrates settlement |

Additional roles:
- **PSP (Payment Service Provider):** a bank (or a TPAP's sponsor bank) authorized to connect to UPI and issue handles (`@okhdfcbank`, `@ybl`, `@paytm`, `@apl`).
- **TPAP (Third-Party App Provider):** apps like Google Pay, PhonePe, Paytm that provide the UI but ride on a **sponsor bank's** PSP license.
- **PPI issuers on UPI:** full-KYC wallets can act as a PSP and interoperate over UPI via a sponsor bank.

```
 Payer app (PSP)                                  Payee app (PSP)
      │                                                 ▲
      ▼                                                 │
 ┌───────────────────────  NPCI UPI switch  ─────────────────────┐
 │  VPA resolution • routing • 2FA orchestration • settlement     │
 └───────────────────────────────────────────────────────────────┘
      │                                                 │
      ▼                                                 ▼
 Payer bank (debit)                              Payee bank (credit)
```

---

## 3) Core building blocks

### 3a) VPA (Virtual Payment Address / UPI ID)
`username@psp` — an alias that maps to a real bank account, so users never share account number/IFSC. Resolution (`ReqValAdd` / address validation) happens at the PSP/NPCI. A user can map multiple accounts to VPAs.

### 3b) MPIN & device binding (2FA in one step)
- On registration the app binds to the **device + SIM** (a silent SMS verifies the mobile number that's linked to the bank account).
- The user sets an **MPIN** with the **issuing bank** (via debit-card + OTP), stored/validated at the **bank**, never by the app.
- Every debit requires the MPIN → **two factors** (device possession + MPIN knowledge) in a **single** action.

### 3c) The NPCI switch
Central router that resolves addresses, routes `ReqPay`/`RespPay`, orchestrates the debit-then-credit, handles time-outs/reversals, and runs settlement. It is the "network" (like Visa/Mastercard for cards) for UPI.

---

## 4) The two payment flows

### 4a) PAY / Push (payer initiates)
Used for scan-and-pay (QR **intent**), send money, most checkouts.

```
1. Payer opens app, scans QR / picks payee VPA, enters amount
2. Payer PSP → NPCI: ReqPay (payer VPA, payee VPA, amount)
3. NPCI resolves payee VPA → beneficiary bank; validates
4. NPCI → payer bank: debit request (validate MPIN, check funds)
5. Payer bank debits, responds success → NPCI
6. NPCI → beneficiary bank: credit request
7. Beneficiary bank credits, confirms → NPCI
8. NPCI returns final status to BOTH PSPs (payer + payee)  ── done in ~seconds
```

### 4b) COLLECT / Pull (payee requests)
Merchant/biller **requests** money; payer approves with MPIN. (e.g. e-commerce "pay via UPI collect", invoices.)

```
1. Payee PSP → NPCI: collect request to payer VPA (amount, note, expiry)
2. NPCI → payer PSP: push notification "approve ₹X to merchant?"
3. Payer approves + enters MPIN
4. From here it follows the PAY debit→credit flow (steps 4–8 above)
```

Collect has an **expiry** and is more prone to phishing (users approving unknown collects), so P2M has shifted toward **intent/QR (push)** and **UPI on merchant pages via deep links**.

### 4c) QR types
- **Static QR:** fixed VPA (amount typed by payer) — small merchants.
- **Dynamic QR:** amount + order id embedded — billed checkouts, easy reconciliation.

---

## 5) The hidden translation layer (UPI ⇄ ISO 8583)

UPI is **JSON/XML over HTTPS** between apps and NPCI, but many **core banking systems** still process on **ISO 8583**. So each bank runs a **UPI adapter / middleware / switch** that:

- Maps UPI JSON → ISO 8583 (**MTI**, data elements, **STAN**, response code **DE39**) and back.
- Validates, enriches, applies HSM PIN/crypto ops.
- Routes into the **Core Banking System (CBS)** / internal payment switch.

```
UPI JSON (PSP→NPCI) ─▶ Bank UPI middleware ─▶ ISO 8583 ─▶ CBS/switch ─▶ debit/credit
                    ◀── JSON ◀── translate ◀── ISO 8583 response ◀──
```

This is why UPI "feels" modern to developers while banks kept decades-old, battle-tested rails — **evolution, not replacement.**

---

## 6) Settlement & reconciliation

- **Authorization/booking is real-time** (payer debited, payee credited within seconds), but **inter-bank settlement** is **deferred net settlement**: NPCI computes net positions across banks and settles in defined windows via **RBI** systems (historically leveraging **NEFT/RTGS**-style settlement); UPI itself is built atop **IMPS** rails.
- **Reconciliation** between the real-time leg and the settlement leg is essential — every bank/PSP reconciles NPCI's raw/settlement files against its own ledger.
- **P2M MDR = 0** (regulatory) for standard UPI — merchants pay effectively nothing, which is central to adoption but shifts cost/ops burden to the ecosystem (incentives, etc.).

---

## 7) Advanced features (UPI 2.0 and beyond)

| Feature | What it does | Engineering note |
| --- | --- | --- |
| **UPI AutoPay (e-mandates)** | Recurring payments (OTT, EMI, SIP, bills) via a **mandate** the user approves once | Mandate has amount/frequency/validity; each execution is a scheduled debit; can pause/modify/revoke. Range ₹1–₹15,000 (executed without re-auth up to the mandate cap) |
| **UPI Lite / Lite X** | Small-value, on-device wallet for **offline / low-latency** micro-payments | Reduces load on core banking + NPCI for tiny txns; balance held on device |
| **Credit Line on UPI (CLOU)** | Pre-sanctioned **bank credit line** as a UPI funding source (RBI-enabled) | Revolving credit: limit drops per spend, replenishes on repayment; **UPI AutoPay** used for repayments; real-time exposure control |
| **RuPay Credit Card on UPI** | Pay from a credit card via UPI QR | Credit rail behind a UPI front-end |
| **UPI Circle** | Delegated payments (family/secondary users on one account) | Delegation with limits/controls |
| **UPI 123Pay** | UPI for **feature phones** (IVR/missed-call/app) | Financial inclusion without smartphones |
| **International UPI** | Cross-border acceptance/linkages (e.g. Singapore PayNow, UAE, others) | NPCI International (NIPL) |

---

## 8) Disputes & failures — UDIR + RBI TAT

UPI has **online dispute resolution** built in via **UDIR (Unified Dispute and Issue Resolution)**:

- Complaints are raised **inside the UPI app** and flow as APIs between PSP/bank switches and NPCI:
  - **ReqChkTxn / RespChkTxn** — check a transaction/dispute status (back-office & auto-update).
  - **ReqComplaint / RespComplaint** — raise/answer a complaint for a financial transaction.
  - **ReqTxnConfirmation / RespTxnConfirmation** — notify final status of auto-update processing.
  - Banks post **TCC** (Transaction Credit Confirmation) or **DRC** (Deemed/Debit Reversal Confirmation) as resolution outcomes.
- **RBI "Harmonisation of TAT"**: failed transactions must be **auto-reversed within a defined turn-around time** (e.g. ~T+1), and banks must **compensate** the customer (₹100/day) for delays beyond TAT — a strong reliability SLA baked into regulation.
- Common failure: **payer debited but payee not credited** → auto-reversal / credit within TAT, tracked by RRN.

---

## 9) Reliability / security / ops lens

- **Security:** device+SIM binding + bank-side MPIN = strong 2FA without OTP friction; VPA hides account details; PIN handled by the **issuer**, not the app; NPCI validates every hop.
- **Reliability:** real-time debit/credit with **guaranteed auto-reversal (TAT)**; deferred net settlement; per-transaction **RRN** for tracing/reconciliation; idempotent handling of retries at PSP/switch.
- **Fraud watch:** **collect-request phishing** (users approving unknown collects) and social-engineering are the main vectors; ecosystem mitigations include collect limits, warnings, and pushing intent/QR over collect.
- **Ops signals:** transaction success rate (NPCI publishes bank-wise **technical decline** stats), TAT compliance, reconciliation breaks, settlement window health, mandate execution success.

---

## 10) UPI vs cards (quick contrast)

| | **Cards (Visa/MC/RuPay)** | **UPI** |
| --- | --- | --- |
| Rails | ISO 8583, four-party | JSON/API via NPCI (+ ISO 8583 into banks) |
| Identifier | PAN / network token | VPA (`name@psp`) |
| Auth | 3DS/OTP (AFA) | Device-bound MPIN (single-step 2FA) |
| Money movement | Auth → capture → settle (T+1..T+3) | Real-time debit/credit; deferred net settlement |
| Merchant cost | MDR (interchange + scheme + acquirer) | **~0 MDR for P2M** |
| Disputes | Chargebacks + reason codes | **UDIR** + RBI TAT auto-reversal/compensation |

---

## 11) Key takeaways

- UPI is an **interoperable, real-time, API-first** rail run by **NPCI** on a **four-pillar** (payer/payee PSP + payer/payee bank) model, atop **IMPS**.
- **VPA** hides bank details; **device+SIM binding + bank-side MPIN** gives **single-step 2FA**; **NPCI** is the central switch.
- Two flows: **PAY/push** (QR intent, dominant for P2M) and **COLLECT/pull** (payee-requested, expiry, phishing-prone).
- Modern JSON meets legacy banks via a **UPI ⇄ ISO 8583 translation layer**; booking is real-time, **settlement is deferred net**.
- Rich feature set — **AutoPay mandates, UPI Lite, Credit Line on UPI, RuPay-CC-on-UPI, Circle, 123Pay, international**.
- Disputes/failures are handled by **UDIR APIs** with **RBI-mandated TAT auto-reversal + compensation** — reliability enforced by regulation.

---

## 12) Quick glossary

- **NPCI:** National Payments Corporation of India — operates UPI.
- **PSP / TPAP / sponsor bank:** service provider / third-party app / the licensed bank it rides on.
- **VPA / UPI ID:** `name@psp` alias mapping to a bank account.
- **MPIN:** UPI PIN set with and validated by the issuing bank.
- **ReqPay / RespPay / ReqValAdd:** core UPI transaction & address-validation APIs.
- **RRN / STAN:** retrieval reference / trace numbers for matching & reconciliation.
- **Deferred net settlement:** batch inter-bank settlement of net positions.
- **AutoPay / mandate:** recurring-payment authorization.
- **CLOU:** Credit Line on UPI (pre-sanctioned bank credit as funding).
- **UDIR:** Unified Dispute and Issue Resolution.
- **TAT:** RBI turn-around-time norm for failed-transaction reversal + compensation.
- **TCC / DRC:** transaction credit confirmation / debit reversal confirmation (dispute outcomes).

---

## 13) Sources & further reading

**NPCI (authoritative)**
- NPCI — *UPI product overview*: <https://www.npci.org.in/what-we-do/upi/product-overview>
- NPCI — *UPI procedural guidelines & circulars*: <https://www.npci.org.in/what-we-do/upi/circular>
- NPCI / BHIM — *UPI AutoPay*: <https://www.bhimupi.org.in/upiautopay.html>
- NPCI — *UPI Lite* / *UPI 123Pay*: <https://www.npci.org.in/what-we-do/upi-lite/product-overview>

**RBI (regulation)**
- RBI — *Operation of pre-sanctioned credit lines through UPI*: <https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12532>
- RBI — *Harmonisation of Turn Around Time (TAT) & customer compensation for failed transactions*: <https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11693>
- RBI — *Prepaid Payment Instruments (PPI) Master Directions* (interoperability): <https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12156>

**Dispute framework**
- Oracle Banking docs — *UPI Unified Dispute and Issue Resolution (UDIR) APIs*: <https://docs.oracle.com/en/industries/financial-services/banking-payments/14.8.0.0.0/payrn/upi-unified-dispute-and-issue-resolution-udir.html>

**Engineering explainers**
- Razorpay — *What is UPI and how it works*: <https://razorpay.com/blog/what-is-upi-and-how-it-works/>
- Wikipedia — *Unified Payments Interface* (four-pillar model, limits, features): <https://en.wikipedia.org/wiki/Unified_Payments_Interface>
- V. Sharma — *ISO 8583 vs REST vs UPI* (translation layer): <https://mvineetsharma.medium.com/iso-8583-vs-rest-apis-vs-upi-architecting-multi-network-payment-systems-in-net-10-2e8708034f9d>
