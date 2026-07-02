# Payment Systems Fundamentals & the Transaction Flow — Detailed Notes

> Companion deep-dive for the summary diagram: `payments-fundamentals-transaction-flow-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand *who* the actors are in an e-commerce payment (the four-party model), *how money actually moves* through the four stages (authorization → capture → clearing → settlement), and *how an order gets confirmed* without lying to the customer.

---

## 1) What "paying online" actually means

When a shopper clicks **Pay**, no money moves yet. What happens is a chain of **messages** between five parties that ends with a *promise* (authorization) and, days later, an *actual money movement* (settlement). E-commerce payments are the engineering discipline of orchestrating those messages **reliably, securely, and exactly once** — even when networks fail mid-request.

Two ideas to anchor everything else:

- **Authorization ≠ money.** Authorization is a real-time *hold/approval* (typically 300–800 ms). Settlement is the actual inter-bank fund movement, usually **T+1 to T+3 days** later.
- **The customer's "order confirmed" screen is a business decision, not a bank fact.** You decide which signal (auth success, capture, or webhook) is trustworthy enough to fulfill an order.

---

## 2) The cast — the four-party (a.k.a. "four-corner") model

| Party | Who it is | Role |
| --- | --- | --- |
| **Cardholder / customer** | The shopper | Owns the card / bank account; initiates payment |
| **Merchant** | The online store | Sells goods; wants to get paid and fulfill the order |
| **Acquirer (acquiring bank / merchant bank)** | e.g. HDFC, Chase Paymentech | Holds the merchant's account; routes auth requests to the network; receives settled funds |
| **Card network / scheme** | Visa, Mastercard, RuPay, Amex | The "switch" in the middle; routes messages between acquirer and issuer; sets rules & interchange |
| **Issuer (issuing bank)** | The customer's bank | Issued the card; decides approve/decline; moves the money; owns the customer relationship |

Two **enabling** players sit *around* the four-party core and are what most engineers actually integrate with:

- **Payment gateway** — the merchant-facing entry point. Captures/tokenizes card data, encrypts it, and forwards the transaction to the processor/acquirer. Think "the front door + secure envelope." (Stripe, Razorpay, PayU, CCAvenue, Paytm all expose a gateway.)
- **Payment processor** — the back-end engine that talks the bank/network protocols (often **ISO 8583**), manages the auth/capture/settlement state machine, and does clearing/reconciliation. Many modern PSPs (Stripe, Razorpay) are gateway **and** processor **and** sometimes acquirer-adjacent.

> **Gateway vs processor vs acquirer** is the #1 confusion. Gateway = secure data intake + routing (mostly at the *merchant* edge). Processor = protocol translation + lifecycle management + settlement. Acquirer = the *licensed bank* that actually holds funds and is a network member. In practice one vendor often wears several hats.

```
 Merchant app
     │  card/UPI/wallet details
     ▼
 [ Payment Gateway ]  ── tokenize + encrypt ──► [ Processor ]
                                                     │ ISO 8583 / API
                                                     ▼
                                              [ Acquirer ] ─► [ Card Network ] ─► [ Issuer ]
```

---

## 3) The four stages of a card transaction

This is the spine of the whole domain. Memorize it.

| Stage | Timing | What happens | Money moves? | Reversible? |
| --- | --- | --- | --- | --- |
| **1. Authorization** | Real-time (300–800 ms) | Issuer checks card validity, funds, fraud rules; places a **hold** and returns an **auth code** | ❌ No (hold only) | ✅ **Void** |
| **2. Capture** | Same day → up to ~7–30 days | Merchant *claims* the authorized amount (can be ≤ auth, e.g. partial ship) | ❌ No | ✅ before settlement |
| **3. Clearing** | End of day (batch) | Network reconciles net positions between issuer & acquirer | ❌ No | ⚠️ rare |
| **4. Settlement** | T+1 to T+3 | Funds move issuer → network → acquirer → merchant, **minus fees** | ✅ **Yes** | ❌ (only chargeback) |

### 3a) Authorization
The gateway sends the transaction (card token, amount, 3DS data, merchant ID, MIT/CIT flag, network token) to the processor → acquirer → network → issuer. The issuer validates and either returns an **approval + auth code** or a **decline code** (e.g. `51` insufficient funds, `05` do not honor). A successful auth *reserves* funds but does not transfer them.

### 3b) Capture (auth-and-capture vs auth-then-capture)
- **Auth + capture (sale):** capture immediately — standard for physical goods shipped fast or digital goods. One step for the merchant, still two internally.
- **Separate capture:** authorize now, capture later (when you ship, or when the final amount is known — hotels, fuel, marketplaces). Authorizations expire (commonly 5–7 days, up to 30), so uncaptured auths are lost.
- **Partial capture / partial ship:** capture less than authorized; the rest is released.

### 3c) Clearing
An end-of-day **batch**: acquirer submits captured transactions; the network computes **net settlement positions** and applies **interchange fees**. Issuer-processors match each clearing record back to its original authorization (Marqeta cites ~99% match vs ~88% industry).

### 3d) Settlement
The issuer debits the cardholder and moves funds via the network to the acquirer, which deposits the **net amount** (transaction total − interchange − scheme fees − acquirer markup) into the merchant account, typically **T+1 to T+3**. This is the only stage where money truly moves.

---

## 4) Fees — where the money leaks (MDR)

The merchant does **not** receive 100%. The **Merchant Discount Rate (MDR)** is split roughly:

- **Interchange** — paid to the **issuer** (largest slice; set by the network).
- **Scheme / network fee** — paid to Visa/Mastercard/RuPay.
- **Acquirer / gateway markup** — the PSP's cut.

This is why "authorization for ₹1000" nets the merchant less than ₹1000 at settlement. (In India, UPI person-to-merchant MDR is largely **zero** by regulation — a key reason UPI exploded; see note 05.)

---

## 5) End-to-end e-commerce checkout flow (happy path)

```
1. Customer clicks "Pay"
2. Merchant BACKEND creates an Order + Payment intent (server-side amount!) ── never trust client price
3. Gateway collects card/UPI/wallet (hosted page or SDK) → tokenizes + encrypts
4. (Card-not-present) 3D Secure challenge if required  ── liability shift, see note 04
5. AUTHORIZATION → issuer approves, returns auth code       [hold placed]
6. CAPTURE (now or on ship)
7. Gateway fires a WEBHOOK: payment.captured / payment.authorized
8. Merchant VERIFIES webhook signature, then marks order PAID  ── source of truth = webhook, not redirect
9. Order confirmation shown / email sent / fulfillment triggered
10. Later: CLEARING (batch) → SETTLEMENT (T+1..T+3) → merchant funded (net of MDR)
```

**Golden rule (from Stripe/Razorpay integration guidance):** *never* derive payment status from the browser redirect / URL params / client callback. The **signed webhook** (or a server-side status fetch) is the only authoritative confirmation. Redirects get lost when the user closes the tab; webhooks are retried.

---

## 6) Order confirmation & state machine

Model the order/payment as an explicit **state machine**, because a payment is a long-running, multi-party workflow that can fail at any hop.

```
 CREATED ─▶ PENDING_AUTH ─▶ AUTHORIZED ─▶ CAPTURED ─▶ SETTLED
    │            │              │             │
    │            └▶ FAILED      └▶ VOIDED     └▶ REFUNDED / DISPUTED
    └▶ ABANDONED
```

- Each transition is an **atomic DB write** (see note 03 on idempotency & outbox).
- **Never** move to `CAPTURED`/PAID on a client signal alone — wait for the verified webhook or a server-side confirm call.
- The dreaded **"orphaned order"**: money left the customer but your DB says unpaid (webhook lost, worker crashed). Fixed by **reconciliation** (note 03) — periodically fetch authoritative status from the PSP and repair local state.

---

## 7) Reliability / security / ops lens

- **Reliability:** treat every payment op as retryable → **idempotency keys** so retries don't double-charge (note 03). Auth can succeed while the *response* is lost — that ambiguity is the core hazard.
- **Security:** card data is toxic. Keep it out of your servers via **tokenization** + hosted fields; comply with **PCI DSS** (note 04). Use **3DS** to shift fraud liability.
- **Ops / observability:** monitor **authorization rate** (approvals/attempts), decline-code mix, capture latency, settlement lag, webhook delivery success, and **reconciliation break count**. A dip in auth rate is often an issuer/BIN/3DS problem, not your code.

---

## 8) Key takeaways

- Payments = orchestrating **messages** among five parties; money only moves at **settlement (T+1..T+3)**, not at "Pay".
- Learn the four stages cold: **authorization → capture → clearing → settlement** (only the last moves money).
- **Gateway ≠ processor ≠ acquirer**, though one vendor often does all three.
- The **webhook (signed), not the browser redirect**, is the source of truth for "paid".
- Model orders as an explicit **state machine** and back it with reconciliation to avoid orphaned orders.
- The merchant nets **amount − MDR** (interchange + scheme + acquirer fees).

---

## 9) Quick glossary

- **Authorization:** real-time issuer approval + fund hold; yields an auth code.
- **Capture:** merchant claims the authorized amount (≤ auth).
- **Clearing:** batch reconciliation of net positions across banks.
- **Settlement:** actual inter-bank money movement to the merchant.
- **Acquirer:** merchant's bank; a network member that receives settled funds.
- **Issuer:** customer's bank; approves/declines and moves money.
- **Gateway:** secure card-data intake + routing at the merchant edge.
- **Processor:** engine speaking bank/network protocols; runs the lifecycle.
- **MDR / interchange:** the fee stack deducted from the merchant.
- **Void / refund / chargeback:** reverse before capture / after settlement (merchant-initiated) / after settlement (issuer-forced).

---

## 10) Sources & further reading

**Transaction lifecycle (auth/capture/clearing/settlement)**
- Stripe — *How card payment processing and settlement works*: <https://stripe.com/en-gb/resources/more/credit-card-payment-authorization-and-transaction-settlement-process>
- Primer — *Understanding the lifecycle of a card payment*: <https://primer.io/blog/understanding-the-lifecycle-of-a-card-payment>
- Payments Mastery — *Authorization & settlement flow / four-party model*: <https://paymentsmastery.com/ecosystem/fundamentals/four-party-model/transaction-flows>
- NMI — *The credit card flow: from swipe to payment*: <https://www.nmi.com/blog/credit-card-flow-the-journey-data-takes-from-swipe-to-payment/>
- Marqeta — *Card program clearing and settlement*: <https://www.marqeta.com/blog/card-program-clearing-and-settlement-how-issuer-processors-manage-fund-flow>

**Gateway / processor concepts & integration flow**
- Razorpay — *Payment Gateway* docs: <https://razorpay.com/docs/payments/payment-gateway/>
- Stripe — *Payment Intents API* (auth/capture lifecycle): <https://docs.stripe.com/payments/paymentintents/lifecycle>
- Stripe — *Place a hold on a card (separate auth & capture)*: <https://docs.stripe.com/payments/place-a-hold-on-a-payment-method>
