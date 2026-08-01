# Post-Training & Alignment: SFT, RLHF & Constitutional AI — Detailed Notes

> Companion deep-dive for the summary diagram: `llm-alignment-rlhf-constitutional-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand **post-training** — how a raw base model (note `03`) becomes the helpful, honest, harmless assistant you chat with. Cover **Supervised Fine-Tuning (SFT)**, **Reinforcement Learning from Human Feedback (RLHF)** with a **reward model + PPO**, the simpler **DPO**, and Anthropic's **Constitutional AI / RLAIF** — the key difference in how **ChatGPT** vs **Claude** are aligned. Finish with how aligned models are **evaluated** (Chatbot Arena, LLM-as-judge).

> This is the stage that "created the ChatGPT era." A base model can autocomplete, but won't reliably follow instructions, refuse harmful requests, or hold a conversation. Alignment fixes that.

---

## 1) Why post-training exists

A **base model** predicts the next token to imitate internet text. Problems when you try to use it as an assistant:

- **Doesn't follow instructions** — asked a question, it might continue with *more questions* (that's plausible internet text).
- **No consistent persona/format** — no notion of a helpful "assistant" turn.
- **Unsafe / unhelpful** — will happily produce harmful, biased, or false content.
- **Miscalibrated to what humans *want*** — likelihood of text ≠ usefulness to a user.

**Goal of alignment (the "3 H's"):** make the model **Helpful, Honest, Harmless.** Two-stage recipe: **SFT → preference optimization (RLHF or Constitutional AI/RLAIF).**

```
BASE model ──▶ SFT (imitate good answers) ──▶ preference optimization (RLHF / RLAIF) ──▶ ASSISTANT
                                                         └── ChatGPT: RLHF (human prefs)
                                                         └── Claude:  Constitutional AI / RLAIF
```

---

## 2) Supervised Fine-Tuning (SFT) — teach the format

**SFT** = continue training the base model (same next-token cross-entropy loss, note `01` §6) on curated **(instruction → ideal response)** pairs written/curated by humans.

- Teaches the **assistant format**: given a user turn, produce a helpful assistant turn.
- **Surprisingly data-efficient:** even ~**1k–10k** high-quality examples meaningfully change behavior (LIMA: "less is more for alignment").
- **What it does / doesn't do:** SFT mostly **re-weights** and **surfaces** knowledge the base model already has and fixes *style/format*. It does **not** inject much new factual knowledge — that came from pretraining.

### Scaling SFT with synthetic data (Alpaca pattern)

Human demonstrations are slow/expensive, so labs bootstrap:

1. Hand-write a small seed set of instructions.
2. Prompt a **strong existing LLM** to generate many more instruction–response pairs.
3. Fine-tune on the synthetic set (**Self-Instruct / Alpaca**).

- Cuts labeling cost dramatically and works well for open models.
- **Diminishing returns:** past a point, more SFT data mainly reinforces style, not capability — motivating **preference-based** methods next.

---

## 3) Why go beyond SFT? The limits of imitation

SFT is **behavior cloning** — it can only be as good as the demonstrations, and humans are often better **judges** than **writers**:

- **Ceiling problem:** it's hard for humans to *write* the ideal answer to a hard coding/medical question, but easy to *pick the better* of two answers.
- **Hallucination pressure:** if SFT targets contain facts the model doesn't actually know, cloning them *teaches it to confidently make things up*.
- **We want to optimize a preference/quality signal**, not just copy examples.

Solution: learn from **comparisons** — *which of these two responses is better?* — via **RLHF** or **Constitutional AI**.

---

## 4) RLHF — Reinforcement Learning from Human Feedback (the ChatGPT recipe)

RLHF (from OpenAI's **InstructGPT**, the basis of ChatGPT) has three steps:

```
① Collect human preferences        ② Train a reward model (RM)       ③ RL-optimize the policy
   prompt → A, B  (LLM samples)        RM(prompt, response) → scalar     maximize RM score
   human picks A ≻ B                   trained to match human ranking    while staying near SFT
                                                                          (PPO + KL penalty)
```

1. **Collect comparisons.** For a prompt, sample several responses; a human **ranks** them (A better than B). Ranking is easier and more consistent than writing.
2. **Train a reward model (RM).** A separate model learns to output a **scalar "how good"** score that matches human preferences (Bradley–Terry loss over pairs).
3. **Optimize the policy with RL.** Use **PPO (Proximal Policy Optimization)** to update the LLM ("policy") to **maximize expected reward** from the RM, with a **KL-divergence penalty** that keeps it close to the SFT model (so it doesn't drift into gibberish that games the RM).

**Why it works:** the model can now exceed the quality of any single human demonstration, because it's optimizing a *learned preference* rather than copying.

**Practical challenges:**
- **Sparse/noisy reward**, **unstable RL** (needs clipping, careful tuning, many tricks).
- **Reward hacking / over-optimization:** the policy exploits RM blind spots (e.g. verbosity, sycophancy). The **KL penalty** and RM re-training push back.
- RLHF turns a **calibrated likelihood model into an optimized policy** — which is why perplexity stops being a useful metric afterward (note `03` §4).

### DPO — Direct Preference Optimization (a simpler alternative)

**DPO** skips the separate reward model and RL loop. Using the same preference pairs, it applies a **single classification-style loss** that directly **raises the likelihood of the preferred response** and **lowers the dispreferred** one (regularized toward the reference model).

- Under standard assumptions, DPO's optimum **coincides** with the RLHF objective.
- **Much simpler & more stable** (plain supervised-style training, no RM, no PPO) → widely used in open models. RLHF/PPO is still used where its extra control helps.

---

## 5) Constitutional AI & RLAIF — the Claude recipe

Anthropic aligns **Claude** with **Constitutional AI (CAI)**, which replaces most **human** harm labels with **AI feedback** guided by a written **"constitution"** (a list of natural-language principles). It has two stages:

### Stage 1 — Supervised (self-critique & revise)

```
harmful prompt ─▶ model drafts a response
              ─▶ model CRITIQUES its draft against a random constitutional principle
              ─▶ model REVISES the response to comply
              ─▶ fine-tune on the revised (safer) responses
```

The model improves its **own** answers by reasoning about the principles — **no human labels the harmful content.**

### Stage 2 — RLAIF (RL from AI Feedback)

```
prompt ─▶ model generates response A, B
       ─▶ an AI judge picks which better follows the constitution (+ chain-of-thought)
       ─▶ AI preferences → train a preference model → RL (PPO) against it
```

This mirrors RLHF's step ③, but the **preference labels for harmlessness come from an AI** applying the constitution, not from human crowdworkers. (Helpfulness preferences may still use human labels — a hybrid PM.)

**Why Anthropic does this:**
- **Scalability:** human harm-labeling is slow, expensive, and exposes annotators to toxic content. AI feedback scales cheaply.
- **Transparency & control:** behavior is governed by an **explicit, editable list of principles** (drawn from sources like the UN Declaration of Human Rights + Anthropic policy) rather than opaque aggregated human labels.
- **Less evasive, better trade-off:** RLHF crowdworkers often reward *"I can't answer that"*, making models over-refuse. CAI produces a model that is **harmless but non-evasive** — it engages and *explains its objections* instead of stonewalling, achieving a better helpfulness-vs-harmlessness frontier.

### ChatGPT (RLHF) vs Claude (Constitutional AI) at a glance

| | **ChatGPT (OpenAI)** | **Claude (Anthropic)** |
| --- | --- | --- |
| Instruction tuning | SFT | SFT (incl. self-revision) |
| Preference source (harmlessness) | **Human** labels (RLHF) | **AI** labels via constitution (**RLAIF**) |
| Governing signal | Learned RM from human rankings | Written **constitution** + RM |
| Optimizer | PPO (and DPO-style methods) | PPO over AI/hybrid preferences |
| Notable trait | Strong instruction following | Explicit principles; harmless **but non-evasive** |

> Both are the *same underlying pipeline* — pretrain → SFT → reward-model-guided RL. The core difference is **where the preference signal comes from**: humans (RLHF) vs an AI applying a constitution (RLAIF).

---

## 6) System prompts — steering at runtime (cheap alignment)

Not all "alignment" is baked into weights. At inference, a hidden **system prompt** sets the assistant's role, style, safety rules, tools, and date. It's how the product layer (note `05`) further shapes behavior **without retraining**. Anthropic even **publishes Claude's system prompts** for transparency. This complements — but doesn't replace — SFT/RLHF/CAI.

---

## 7) Evaluating aligned models (perplexity no longer works)

After alignment the model is an **optimized policy**, not a calibrated distribution, and prompts have **many** valid open-ended answers — so perplexity/loss are poor comparators. Instead:

- **Human pairwise preference — Chatbot Arena (LMSYS):** users chat with two anonymous models and vote; **Elo ratings** rank them. Blind and open-ended, but subject to **user-population bias** (tech-savvy prompts) and cost/latency.
- **LLM-as-judge (e.g. AlpacaEval, MT-Bench):** a strong model (e.g. GPT-4) does automated pairwise judging. **~high agreement** with human majority at a fraction of cost — but has **biases** (favors longer/verbose answers, position bias) that need statistical controls (e.g. length-controlled AlpacaEval).
- **Capability/safety suites:** targeted benchmarks + red-teaming for refusals, jailbreaks, and harms.

---

## 8) Human-labeling challenges (why RLAIF is attractive)

- **Slow & expensive**, and **annotators disagree** (~60–70% inter-annotator agreement is common).
- **Confounds:** labelers reward **length/style/confidence** over correctness → models learn **verbosity and sycophancy**.
- **Ethical cost:** exposure to toxic content.
- **Mitigations:** careful **annotation guidelines**, annotator selection, statistical de-biasing — and increasingly, **AI feedback (RLAIF)** to reduce human load.

---

## 9) Key takeaways

- **Post-training turns a base model into an assistant** via **SFT** (teach format, data-efficient) then **preference optimization**.
- **SFT is behavior cloning** — limited by human writing ability and can *teach hallucination* if targets exceed the model's knowledge.
- **RLHF (ChatGPT):** humans **rank** outputs → **reward model** → **PPO** with a **KL leash**; lets the model beat individual human demos but risks **reward hacking**.
- **DPO** achieves RLHF's goal with a **single supervised-style loss** — simpler and more stable, no RM/PPO.
- **Constitutional AI / RLAIF (Claude):** replaces human harm labels with **AI feedback guided by a written constitution** (self-critique/revise + AI-judged preferences) → scalable, transparent, and **harmless-but-non-evasive**.
- **Aligned models need new evals** — **Chatbot Arena** (human Elo) and **LLM-as-judge** — because perplexity no longer applies.

---

## 10) Quick glossary

- **Alignment:** shaping a model to be helpful, honest, harmless.
- **SFT:** supervised fine-tuning on instruction→response pairs.
- **Behavior cloning:** imitating demonstrations directly.
- **RLHF:** RL from Human Feedback — reward model + PPO on human preferences.
- **Reward model (RM):** predicts a scalar quality score from human/AI preferences.
- **PPO:** the RL optimizer used to maximize reward with a stability clip.
- **KL penalty:** keeps the policy close to the SFT model to avoid degenerate reward hacking.
- **DPO:** Direct Preference Optimization — RLHF's goal via one closed-form loss.
- **Constitutional AI (CAI):** Anthropic's method: align to a written set of principles.
- **RLAIF:** RL from AI Feedback — AI (not humans) provides preference labels.
- **Chatbot Arena:** blind human pairwise voting → Elo leaderboard.
- **LLM-as-judge:** using a strong LLM to score/compare outputs.

---

## 11) Sources & further reading

**Primary source (this series)**
- Stanford CS229 — *Building Large Language Models (LLMs)*: <https://youtu.be/9vM4p9NN0Ts>

**RLHF / instruction tuning (ChatGPT lineage)**
- Ouyang et al., *InstructGPT — Training LMs to follow instructions with human feedback*: <https://arxiv.org/abs/2203.02155>
- Christiano et al., *Deep RL from Human Preferences*: <https://arxiv.org/abs/1706.03741>
- OpenAI, *Aligning language models to follow instructions* (blog): <https://openai.com/index/instruction-following/>
- Schulman et al., *Proximal Policy Optimization (PPO)*: <https://arxiv.org/abs/1707.06347>
- Rafailov et al., *Direct Preference Optimization (DPO)*: <https://arxiv.org/abs/2305.18290>
- Zhou et al., *LIMA — Less Is More for Alignment*: <https://arxiv.org/abs/2305.11206>
- Taori et al., *Alpaca* / Wang et al., *Self-Instruct*: <https://crfm.stanford.edu/2023/03/13/alpaca.html> · <https://arxiv.org/abs/2212.10560>

**Constitutional AI / RLAIF (Claude lineage)**
- Bai et al., *Constitutional AI: Harmlessness from AI Feedback*: <https://arxiv.org/abs/2212.08073>
- Anthropic, *Constitutional AI* (overview): <https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback>
- Anthropic, *Claude's Constitution*: <https://www.anthropic.com/news/claudes-constitution>
- Bai et al., *Training a Helpful and Harmless Assistant with RLHF*: <https://arxiv.org/abs/2204.05862>
- Anthropic, *Claude system prompts* (transparency): <https://docs.anthropic.com/en/release-notes/system-prompts>

**Evaluation of aligned models**
- Chiang et al., *Chatbot Arena*: <https://arxiv.org/abs/2403.04132>
- Zheng et al., *MT-Bench / LLM-as-a-judge*: <https://arxiv.org/abs/2306.05685>
- Dubois et al., *AlpacaEval / length-controlled AlpacaEval*: <https://arxiv.org/abs/2404.04475>
