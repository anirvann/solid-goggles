# Pretraining: Data, Loss, Evaluation & Scaling Laws — Detailed Notes

> Companion deep-dive for the summary diagram: `llm-pretraining-data-scaling-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Understand **pretraining** — the massive, expensive first stage that produces a *base model* from raw internet text. Cover the **data pipeline** (crawl → extract → filter → dedup → weight), the **loss** (cross-entropy) and how we **evaluate** base models (**perplexity**, **MMLU/HELM**, contamination), and the **scaling laws** (Kaplan, **Chinchilla** ~20 tokens/param) that decide how big a model and how much data to use for a compute budget.

> This is the heart of the CS229 lecture. Its recurring theme: **data, evaluation, and systems matter more in practice than architecture tweaks.**

---

## 1) What pretraining produces

Pretraining runs next-token prediction (notes `01`–`02`) over **trillions of tokens** to produce a **base model**: a general next-token predictor with broad knowledge and latent skills, but **not** yet a helpful/safe assistant (that's post-training, note `04`).

The five levers that determine a model's real-world quality (per the lecture):

1. **Architecture** — usually a Transformer variant (note `02`).
2. **Training loss & algorithm** — cross-entropy + optimizer.
3. **Data** — what text, how much, how clean. ← *often the biggest differentiator*
4. **Evaluation** — how you measure progress.
5. **Systems** — hardware/software efficiency (note `05` covers inference systems; training systems below).

> Academia over-indexes on (1); industry wins are dominated by (3), (4), (5).

---

## 2) The pretraining objective (recap + scale)

- **Objective:** minimize **cross-entropy** on next-token prediction (note `01` §6) — equivalently, maximize the log-likelihood of the corpus.
- **Self-supervised:** the label is the actual next token, so **no human annotation** is needed → you can consume the whole internet.
- **Scale:** frontier base models train on the order of **10–20+ trillion tokens** (Llama 3 ≈ 15T). Raw crawl before filtering is **petabytes** across **hundreds of billions of web pages**.

Emergence: to keep pushing loss down over that much text, the model must implicitly learn grammar, facts, translation, arithmetic, and rudimentary reasoning — none of which are explicitly supervised.

---

## 3) The data pipeline — from raw web to clean corpus

**Garbage in, garbage out.** Turning Common Crawl into a training set is a multi-stage cleaning problem, and it is where much of the secret sauce lives.

| Stage | What it does | Why it matters |
| --- | --- | --- |
| **1. Crawl** | Start from **Common Crawl** (~250B pages, petabytes) or a private crawl | The raw firehose of text |
| **2. Text extraction** | Strip HTML/boilerplate/ads/JS; keep real content | Hard: math, tables, code extract poorly |
| **3. Safety / blacklist filtering** | Remove NSFW, harmful, PII, blacklisted domains | Safety + legal + quality |
| **4. Deduplication** | Drop duplicate pages, headers/footers, repeated books | Dupes waste compute & cause memorization/overfitting |
| **5. Heuristic quality filters** | Rules on length, symbol/word ratios, weird token distributions | Cheap removal of junk pages |
| **6. Model-based quality filter** | Train a classifier on "good" references (e.g. Wikipedia-like) to score pages | Keeps authoritative, well-written text |
| **7. Domain classification & reweighting** | Classify into domains (code, books, web, academic…) and **upweight** high-value ones | More code/books → better reasoning & coding |
| **8. Final high-quality anneal** | End training with a pass over top-quality data (e.g. Wikipedia, curated) | Sharpens the quality "tail" |

```
Common Crawl ─▶ extract text ─▶ filter (safety/heuristics/model)
             ─▶ deduplicate ─▶ classify + reweight domains ─▶ final clean corpus ─▶ TRAIN
```

- **Representative corpora:** The Pile, C4, RefinedWeb, Dolma, FineWeb.
- Data work is **resource-intensive and secretive** — labs rarely disclose their exact mix because it's a competitive edge.

---

## 4) Evaluating a base model

### Perplexity

The natural in-house metric: **perplexity = exp(cross-entropy loss)** = the exponentiated average per-token negative log-likelihood.

- **Intuition:** the effective number of tokens the model is "hesitating" between at each step. **Lower is better.**
- **Bounds:** `1` (perfect) up to `~|V|` (maximally uncertain). Perplexity fell dramatically from 2017→2023 as scale grew.
- **Limitation:** it depends on the **tokenizer** and the **exact test set**, so perplexity is **not comparable across different models/tokenizers** — great for tracking *your own* progress and ablations, poor for public leaderboards.

### Task benchmarks (MMLU, HELM, …)

Because perplexity isn't comparable, base models are ranked on **suites of automatically-scored tasks**:

- **MMLU** — 57 subjects of multiple-choice questions (law, medicine, physics…), the de-facto "how smart is it" exam.
- **HELM**, **Hugging Face Open LLM Leaderboard** — aggregate many tasks.
- **Scoring trick:** for multiple-choice, compare the model's **likelihood of each candidate answer** (or restrict generation to the options) and pick the highest — no free-form judging needed.

### Evaluation pitfalls

- **Inconsistent protocols:** the *same* benchmark scored differently across labs (prompt format, few-shot count) → divergent numbers.
- **Train–test contamination:** benchmark questions leak into the training corpus, inflating scores. **Detection heuristic:** compare the joint likelihood of test examples in their **original order** vs a **random permutation** — much higher likelihood in original order suggests the model saw that exact data.

---

## 5) Scaling laws — the superpower of predictability

**Scaling laws** are the empirical finding that test loss improves **predictably** (as a smooth **power law**) as you increase **compute (FLOPs)**, **model size (parameters)**, and **data (tokens)**.

```
log(loss)
   │  ●
   │    ●
   │       ●___
   │           ●___          straight line on log–log axes
   │               ●____
   └────────────────────── log(compute / params / data)
```

- **Why it's a superpower:** you can train **small** models, fit the curve, and **extrapolate** to predict a giant model's loss **before** spending millions on the full run.
- **Modern pipeline:** don't tune hyperparameters directly on the giant model. Instead, find a **scaling recipe** on smaller models and extrapolate.
- **Caveat:** scaling laws are empirical, not fully theoretically grounded; possible plateaus/regime changes aren't ruled out.

### Chinchilla — compute-optimal allocation

Given a **fixed compute budget**, should you train a **bigger model on less data** or a **smaller model on more data**? DeepMind's **Chinchilla** answered by varying model size and tokens at fixed FLOPs:

- **Optimal ratio ≈ 20 tokens per parameter** to minimize training loss. (A 70B model → ~1.4T tokens.)
- Chinchilla (70B, compute-optimal) **beat** Gopher (280B, undertrained) at equal compute → many earlier models were **too big and under-trained**.
- **Inference economics shift the target:** if a model will serve billions of requests, you'd rather have a **smaller model trained on far more data** (~**150 tokens/param** or more). Smaller = cheaper/faster **forever** at inference, so labs deliberately "over-train" past the 20:1 training optimum (e.g. Llama 3 8B on 15T tokens ≈ ~1875:1).

```
FLOPs ≈ 6 · N(params) · D(tokens)          ← handy back-of-envelope for training cost
```

---

## 6) Cost, compute & the systems lens (training)

- **FLOPs ≈ 6 × params × tokens.** From FLOPs and measured **throughput** (× GPU count × utilization) you estimate GPU-hours → wall-clock days → **$**.
- **Order of magnitude:** frontier runs cost **tens of millions of dollars**, thousands of GPUs, weeks–months. Each generation tends to demand **~10× more compute** than the last, with material energy/carbon footprints.
- **Real GPU utilization** of a well-tuned run is only **~40–50%** of peak FLOPs — the rest is lost to memory bandwidth, communication, and pipeline bubbles.

**Systems techniques that make training feasible:**
- **Mixed / low precision** (FP16/BF16, FP8) — halve memory & bandwidth, speed up matmuls; keep master weights in higher precision for stability.
- **Operator / kernel fusion** (e.g. `torch.compile`, FlashAttention) — combine ops to cut GPU↔memory round-trips.
- **Parallelism at scale:** **data**, **tensor**, **pipeline**, and **sequence/context** parallelism + sharded optimizer states (ZeRO/FSDP), with **all-reduce** communication tuned to the network.
- **Tiling & memory locality** to keep the tensor cores fed.

---

## 7) End-to-end pretraining flow

```
1. Build corpus:  crawl ─▶ extract ─▶ filter ─▶ dedup ─▶ reweight domains ─▶ tokenize
2. Pick config:   use scaling laws + Chinchilla (adjusted for inference) → choose N and D
3. Train:         next-token cross-entropy over D tokens on a big GPU cluster
                  (mixed precision + fused kernels + data/tensor/pipeline parallelism)
4. Track:         loss / perplexity curves; periodic MMLU/HELM checks; watch for divergence
5. Output:        a BASE model  ─▶  (hand off to post-training, note 04)
```

**Risks:** dirty/duplicated data (memorization, benchmark contamination), loss divergence/spikes, low precision numerical issues, under-training relative to model size, and choosing a train-optimal size that's too expensive to serve.

---

## 8) Key takeaways

- Pretraining = **self-supervised next-token prediction over trillions of tokens** → a **base model**.
- **Data quality dominates.** The pipeline (extract → filter → dedup → reweight → high-quality anneal) is where labs differentiate and stay secretive.
- **Perplexity** (= `exp(loss)`) tracks your own progress but **isn't comparable across tokenizers**; use **MMLU/HELM** for cross-model ranking — watching out for **inconsistent protocols** and **contamination**.
- **Scaling laws** make loss **predictable** in compute/params/data — you extrapolate from small models instead of gambling on the big run.
- **Chinchilla:** compute-optimal ≈ **20 tokens/param**; but **inference cost** pushes real products to **over-train smaller models** (100–1000+ tokens/param).
- Training is a **systems problem**: mixed precision, kernel fusion, and multi-dimensional parallelism turn a theoretical FLOP count into a finished model at ~40–50% hardware utilization.

---

## 9) Quick glossary

- **Base model:** pretrained next-token predictor before alignment.
- **Common Crawl:** open, petabyte-scale web crawl; the usual raw data source.
- **Deduplication:** removing repeated text to save compute and reduce memorization.
- **Perplexity:** `exp(cross-entropy)`; effective branching factor per token (lower = better).
- **MMLU:** 57-subject multiple-choice benchmark used to rank general knowledge/reasoning.
- **Contamination:** benchmark data leaking into training, inflating scores.
- **Scaling law:** power-law relating loss to compute/params/data.
- **Chinchilla-optimal:** the compute-optimal params↔tokens balance (~20 tokens/param).
- **FLOPs:** floating-point operations; `≈ 6·N·D` for training.
- **Mixed precision:** training in FP16/BF16/FP8 with higher-precision master weights.
- **Operator fusion:** merging GPU ops into one kernel to cut memory traffic.

---

## 10) Sources & further reading

**Primary source (this series)**
- Stanford CS229 — *Building Large Language Models (LLMs)*: <https://youtu.be/9vM4p9NN0Ts>

**Scaling laws**
- Kaplan et al., *Scaling Laws for Neural Language Models*: <https://arxiv.org/abs/2001.08361>
- Hoffmann et al., *Training Compute-Optimal LLMs (Chinchilla)*: <https://arxiv.org/abs/2203.15556>

**Data pipelines & corpora**
- Gao et al., *The Pile*: <https://arxiv.org/abs/2101.00027>
- Penedo et al., *RefinedWeb*: <https://arxiv.org/abs/2306.01116>
- Penedo et al., *FineWeb*: <https://arxiv.org/abs/2406.17557>
- Raffel et al., *C4 / T5 (Exploring the Limits of Transfer Learning)*: <https://arxiv.org/abs/1910.10683>
- Common Crawl: <https://commoncrawl.org/>

**Models / reports**
- *GPT-3 — Language Models are Few-Shot Learners*: <https://arxiv.org/abs/2005.14165>
- *The Llama 3 Herd of Models*: <https://arxiv.org/abs/2407.21783>

**Evaluation**
- Hendrycks et al., *Measuring Massive Multitask Language Understanding (MMLU)*: <https://arxiv.org/abs/2009.03300>
- Liang et al., *HELM — Holistic Evaluation of Language Models*: <https://arxiv.org/abs/2211.09110>
