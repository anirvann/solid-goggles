# Security, Fraud & Disputes — Detailed Notes

> Companion deep-dive for the summary diagram: `payments-security-fraud-disputes-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand the security stack that protects money and card data — **PCI DSS**, **tokenization**, **encryption/HSM**, **3D Secure** — plus how **fraud detection** and the **chargeback/dispute lifecycle** (including representment & liability shift) actually work.

---

## 1) Three layers of the same strategy

Payment security is not three separate problems; it's three complementary layers:

1. **Protect the environment** → **PCI DSS** (governance + controls).
2. **Neutralize stolen data** → **tokenization + encryption** (make the data useless if leaked).
3. **Move fraud liability & catch fraud** → **3D Secure + fraud models + dispute handling**.

---

## 2) PCI DSS — the compliance baseline

**PCI DSS** (Payment Card Industry Data Security Standard) is a set of technical + operational requirements from the card brands (Visa, Mastercard, Amex, Discover, JCB) to protect **cardholder data**. It is **not a law**, but non-compliance carries real penalties (card-network fines) and breach liability. Current version **v4.0** (mandatory since March 2024; v4.0.1 clarifications ongoing).

**The Cardholder Data Environment (CDE)** = any system that **stores, processes, or transmits** PAN. Everything in the CDE is *in scope*. The whole game is **scope reduction**:

- Use **hosted fields / iframes / redirect** so the PAN goes straight to the PSP and **never touches your servers** → you qualify for the lighter **SAQ A** self-assessment.
- **Never store** PAN, CVV, or full track data. CVV must **never** be stored post-auth.
- **Segment** the CDE from the rest of the network.
- **Separation of duties:** token users/admins must not have access to PAN at capture or elsewhere.

The 12 PCI DSS requirements (grouped): build/maintain a secure network (firewalls, no vendor defaults), protect stored data (encryption, key management), protect data in transit (strong TLS), vulnerability management (anti-malware, secure dev), strong access control (need-to-know, MFA, physical), monitor & test (logging, scanning, pen-tests), and an information-security policy.

---

## 3) Tokenization — make stolen data worthless

Tokenization replaces the PAN with a **token** that has no exploitable value outside its system. Two kinds (see also note 02):

| | **PSP / vault token** | **Network token (VTS / MDES)** |
| --- | --- | --- |
| Issued by | Gateway/PSP vault | Card network (Visa VTS, Mastercard MDES) |
| Value | Charge later without holding PAN | Merchant/device-bound PAN replacement |
| Extra wins | Cuts PCI scope | **Auto-updates on card reissue**, lifts auth rates, carries cryptogram provenance |

Key PCI nuances (from the PCI Tokenization guidance):
- If a token **cannot** be exchanged for the PAN and the PAN is never returned, the token can be **out of CDE scope**.
- But a **high-value token** that can itself **initiate a transaction** ("token as payment instrument") may still be in scope and needs extra controls — it can be monetized like the PAN.

**India specifics — CoFT:** RBI's **Card-on-File Tokenization** mandate means merchants/aggregators **cannot store actual card numbers**; saved cards must be **network tokens**. This pushed Indian e-commerce fully onto network tokenization.

**Important:** tokenization protects **data**, it does **not** by itself stop fraud — a valid token used by a fraudster still transacts. That's what 3DS and fraud models are for.

---

## 4) Encryption, HSM & key management

- **In transit:** TLS 1.2/1.3 everywhere; **P2PE** (point-to-point encryption) for card-present.
- **At rest:** encrypt sensitive data; keys managed in a **KMS/HSM**, rotated, with split knowledge/dual control.
- **HSM (Hardware Security Module):** performs **PIN-block** encryption/translation, **MAC** gen/verify, and **cryptogram validation**; holds keys in tamper-resistant hardware. Mandatory for PIN and network-cryptogram operations.
- **Secrets:** API keys, webhook secrets, signing keys live in a secrets manager, never in code.

---

## 5) 3D Secure (3DS2 / EMV 3DS) — authentication + liability shift

**3D Secure** adds an issuer-side **authentication** step to card-not-present transactions across **three domains**: issuer (customer's bank), acquirer (merchant's bank), interoperability (the network). The "3 domains" is the name's origin.

**3DS2 (EMV 3DS)** is risk-based:
- Merchant/gateway sends a **rich data payload** (100+ signals: device, browser, behavior, prior history) to the issuer's **ACS** (Access Control Server).
- **Frictionless flow:** low-risk → issuer approves silently (target 75%+ frictionless to keep checkout fast).
- **Challenge flow:** suspicious → OTP / biometric / bank-app push.

**The commercial payoff = liability shift.** When a 3DS-authenticated transaction is later disputed as **fraud** (Visa reason code **10.4**, Mastercard **4837**), financial liability shifts from **merchant → issuer**. The shift applies when authentication is **successful** (Visa **ECI 05**) or, with limits, **attempted** (ECI 06); the merchant submits the **ECI** in the authorization to claim it.

**Caveats:**
- Liability shift covers **fraud (10.x)** chargebacks **only** — *not* non-fraud disputes (goods not received, defective, duplicate charge).
- In EEA/UK, 3DS/SCA is **mandatory** under **PSD2 Strong Customer Authentication**; in the US it's optional but attractive. In India, an **OTP-based additional factor of authentication (AFA)** has long been mandated by RBI for CNP card transactions.
- **Network tokens + 3DS** compound: token provenance lets issuers skip challenges more often → frictionless rates 5–15 points higher than raw PAN.

---

## 6) Fraud detection

Fraud prevention sits *alongside* authentication (a valid card can still be fraud):

- **Rules engine:** velocity limits, geo/BIN mismatches, blocklists, amount thresholds, AVS/CVV checks.
- **ML risk scoring:** device fingerprint, behavioral signals, historical patterns → risk score → allow / challenge (route to 3DS) / block. (Stripe Radar, Razorpay/Signifyd-style engines.)
- **Signals:** IP, device id, email/phone reputation, prior successful transactions, network-token/cryptogram trust.
- **Trade-off:** too strict → **false declines** (lost revenue, the bigger cost for many merchants); too loose → fraud + chargebacks. Tune to a target **fraud bps** and **decline rate**; use 3DS **data-only** to feed issuer models without adding challenge friction.

---

## 7) The chargeback / dispute lifecycle

A **chargeback** is a **forced reversal** initiated by the cardholder via their **issuer** after settlement — distinct from a merchant-initiated **refund**.

```
Cardholder disputes ─▶ Issuer raises chargeback (reason code) ─▶ funds pulled from merchant
        │
        ▼
Merchant: ACCEPT (concede)  OR  REPRESENT (fight with evidence)
        │ represent
        ▼
Acquirer submits evidence ─▶ Issuer reviews ─▶ win (funds returned) / lose
        │ escalate
        ▼
 Pre-arbitration ─▶ Arbitration (network decides, fees at stake)
```

**Stages / terms:**
- **Retrieval request** (sometimes first): issuer asks for transaction info.
- **Chargeback + reason code:** e.g. Visa **10.4** (fraud – CNP), **13.1** (merchandise not received), **13.3** (defective), **12.6** (duplicate processing).
- **Representment:** merchant submits **compelling evidence** to prove legitimacy — evidence depends on the reason code (auth records, device fingerprint/IP for fraud; **proof of delivery / tracking** for non-receipt; signed terms for subscriptions). Typical window: **~30 calendar days**.
- **Pre-arbitration / arbitration:** if the issuer isn't satisfied, escalation; the network arbitrates and losing party pays fees.

**Visa Compelling Evidence 3.0 (CE 3.0):** for fraud (10.4) disputes, a merchant can win by proving a **prior trust relationship** — **two prior undisputed transactions** from the same cardholder sharing **two matching data points** (e.g. device fingerprint + IP, or account/shipping). This can **auto-reverse** fraud chargebacks, so log device/IP/account on every order.

**Chargeback economics:** beyond the lost amount, each chargeback carries a **fee**; sustained **chargeback ratio > ~1%** flags you as **high-risk** (Visa VDMP / Mastercard programs), raising processing costs or risking account termination. **Prevention** (3DS liability shift, clear billing descriptors, good CS, delivery tracking, fraud scoring) beats fighting.

---

## 8) Reliability / security / ops lens

- **Reduce scope, reduce blast radius:** hosted fields + tokenization keep PAN out of your systems (smaller CDE, smaller breach).
- **Defense in depth:** PCI controls + encryption/HSM + 3DS + fraud scoring + dispute automation — no single layer suffices.
- **Observability:** fraud rate (bps), false-decline rate, 3DS frictionless %, chargeback ratio & win rate, representment SLA adherence, PCI scan/pentest status.
- **Data hygiene for disputes:** persist device fingerprint, IP, auth/ECI results, delivery tracking, and consent artifacts — they're your evidence.

---

## 9) Key takeaways

- **PCI DSS** governs cardholder data; the winning move is **scope reduction** via hosted fields + tokenization + never storing PAN/CVV.
- **Tokenization** makes leaked data useless but does **not** stop fraud; **network tokens** also lift auth rates (India: **CoFT** mandates them).
- **3DS2** authenticates the cardholder and, on **fraud** disputes, **shifts liability to the issuer** (ECI 05/06); it does **not** cover non-fraud disputes.
- **Fraud detection** = rules + ML risk scoring; the real cost is often **false declines**, so tune carefully.
- **Chargebacks** are issuer-forced reversals with **reason codes**; fight via **representment / CE 3.0**, but **prevention** (keep ratio < ~1%) is cheaper.

---

## 10) Quick glossary

- **PCI DSS / CDE:** card-data security standard / the systems that touch PAN.
- **PAN / CVV:** card number / card verification value (never store CVV).
- **Tokenization:** replace PAN with a valueless token (PSP vault or network token).
- **HSM / P2PE:** hardware crypto module / point-to-point encryption.
- **3DS2 (EMV 3DS) / ACS / ECI:** CNP authentication / issuer auth server / e-commerce indicator claiming liability shift.
- **SCA:** Strong Customer Authentication (PSD2, EEA/UK).
- **Chargeback / reason code:** issuer-forced reversal + its cause code.
- **Representment / CE 3.0:** contesting a chargeback with evidence / Visa prior-transaction rule.
- **Liability shift:** fraud loss moves merchant → issuer on 3DS-authenticated transactions.

---

## 11) Sources & further reading

**PCI DSS & tokenization**
- PCI SSC — *PCI DSS v4.0.1* (official docs library): <https://www.pcisecuritystandards.org/document_library/>
- PCI SSC — *Tokenization Product Security Guidelines / Information Supplement* (PDF): <https://listings.pcisecuritystandards.org/documents/Tokenization_Guidelines_Info_Supplement.pdf>
- RBI — *Card-on-File Tokenisation (CoFT) FAQs*: <https://www.rbi.org.in/Scripts/FAQView.aspx?Id=161>
- Visa — *Visa Token Service*: <https://developer.visa.com/capabilities/vts>

**3D Secure / authentication**
- EMVCo — *EMV 3-D Secure specifications*: <https://www.emvco.com/emv-technologies/3-d-secure/>
- KeyTransact — *3D Secure (3DS2) implementation guide* (ECI/liability shift): <https://www.keytransact.com/guides/3d-secure>
- Stripe — *3D Secure & SCA*: <https://docs.stripe.com/payments/3d-secure>

**Fraud & disputes / chargebacks**
- Stripe — *Radar / fraud prevention*: <https://docs.stripe.com/radar>
- Stripe — *Disputes and fraud*: <https://docs.stripe.com/disputes>
- Inyo — *Chargeback management guide for payment processors (2026)* (reason codes, representment, CE 3.0): <https://www.inyoglobal.com/news/chargeback-management-guide>
- Visa — *Dispute management / Visa Resolve Online*: <https://usa.visa.com/support/small-business/disputes.html>
