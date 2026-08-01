# The Transformer Architecture & Attention — Detailed Notes

> Companion deep-dive for the summary diagram: `llm-transformer-attention-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Open the box labeled "Transformer" from note `01` and understand the machinery that turns token embeddings into next-token predictions: **self-attention (Q/K/V)**, **multi-head attention**, the **feed-forward network**, **residual connections + layer norm**, **positional information**, and why ChatGPT/Claude use a **decoder-only** stack. Understand where the **context window** and the **quadratic cost** come from.

> Almost every modern LLM (GPT, Claude, Gemini, Llama) is a variant of the **Transformer** introduced in *Attention Is All You Need* (2017). The CS229 lecture treats the Transformer as assumed background; this note fills it in.

---

## 1) Big picture: a decoder-only Transformer

ChatGPT and Claude are **decoder-only** Transformers: a stack of `N` identical layers (GPT-3 had 96; frontier models more) that each refine a sequence of token vectors, followed by an LM head that predicts the next token.

```
tokens ─▶ [ Token Embedding + Positional Info ]
        ─▶ ┌───────────────── Transformer block × N ─────────────────┐
           │  x ─▶ LayerNorm ─▶ Multi-Head Self-Attention ─▶ (+x)     │  ← residual
           │  h ─▶ LayerNorm ─▶ Feed-Forward (MLP)        ─▶ (+h)     │  ← residual
           └──────────────────────────────────────────────────────────┘
        ─▶ Final LayerNorm ─▶ [ LM head (unembed) ] ─▶ logits ─▶ softmax
```

Two sub-layers do all the work in each block:
- **Self-attention** — tokens **exchange information** ("look at" each other).
- **Feed-forward network (FFN/MLP)** — each token is **transformed independently** (where much stored "knowledge" lives).

Everything else (residuals, normalization, positions) exists to make this **trainable at depth and scale**.

---

## 2) Self-attention — the core idea

The problem: the vector for "it" in *"The trophy didn't fit in the suitcase because **it** was too big"* must incorporate "trophy". Attention is the mechanism that lets each token **pull in relevant information from other tokens**.

For every token, the model computes three vectors via learned projections `W_Q, W_K, W_V`:

- **Query (Q):** "what am I looking for?"
- **Key (K):** "what do I contain / offer?"
- **Value (V):** "what information do I pass along if attended to?"

**Attention = a soft, content-based lookup.** Each token's query is compared (dot product) against every token's key to produce **attention weights**; the output is the weighted sum of **values**:

```
Attention(Q, K, V) = softmax( (Q · Kᵀ) / √d_k ) · V
```

- `Q · Kᵀ` → a score for every (query token, key token) pair = "how relevant is token j to token i?"
- `√d_k` scaling keeps dot products from getting huge (stabilizes softmax gradients).
- `softmax` over each row → weights that sum to 1.
- Multiply by `V` → each token's new representation is a **blend of the values it cared about**.

### Causal (masked) attention

In a decoder, token `i` may only attend to tokens `≤ i` (the past), never the future — otherwise predicting the next token would be cheating. This is enforced with a **causal mask** that sets future scores to `−∞` before softmax.

```
        keys →  t1  t2  t3  t4
queries t1     [ ✓   ·   ·   · ]     ✓ = allowed
        t2     [ ✓   ✓   ·   · ]     · = masked (−∞)
        t3     [ ✓   ✓   ✓   · ]
        t4     [ ✓   ✓   ✓   ✓ ]
```

---

## 3) Multi-head attention

One attention operation can only capture one "kind" of relationship. **Multi-head attention** runs `h` attention operations **in parallel**, each with its own smaller `W_Q/W_K/W_V`, then concatenates and projects the results.

- Different heads specialize: some track **syntax** (subject↔verb), some track **coreference** (pronoun↔noun), some copy **nearby tokens**, etc.
- Heads operate in lower-dimensional subspaces (`d_model / h` each), so total compute is similar to one full-size head.
- **MQA / GQA** (multi-query / grouped-query attention) are modern variants that **share K/V across heads** to shrink the KV cache at inference (see note `05`).

```
        ┌─ head 1 (Q1,K1,V1) ─┐
input ─▶ ┼─ head 2 (Q2,K2,V2) ─┼─▶ concat ─▶ W_O ─▶ output
        └─ …  head h        ──┘
```

---

## 4) Feed-forward network (FFN / MLP)

After tokens mix via attention, each token vector is pushed **independently** through a 2-layer MLP (same weights for every position):

```
FFN(x) = W₂ · activation( W₁ · x )      activation = GELU / SwiGLU
```

- The hidden dimension is typically **~4× `d_model`** (expand → nonlinearity → project back).
- This is where a large share of the **parameters** live and where much **factual/skill "memory"** is stored.
- Attention = *communication between tokens*; FFN = *per-token computation*. Alternating them repeatedly builds rich representations.

---

## 5) Residual connections & normalization (why deep nets train)

Stacking dozens–hundreds of layers only works because of two tricks:

- **Residual (skip) connections:** each sub-layer computes `x + SubLayer(x)`. Gradients flow through the "+x" highway, preventing vanishing gradients and letting layers make **incremental** refinements (the "residual stream" is the model's shared workspace).
- **Layer normalization:** normalizes activations to keep their scale stable. Modern LLMs use **pre-norm** (LayerNorm *before* each sub-layer) and often **RMSNorm** for stability at scale.

```
x ─▶ LN ─▶ Attention ─▶ + ─▶ LN ─▶ FFN ─▶ +  ─▶ (next block)
└──────────────────────┘        └────────────┘
     residual highway                residual
```

---

## 6) Positional information (order matters)

Self-attention is **permutation-invariant** — by itself it can't tell "dog bites man" from "man bites dog". Position must be injected explicitly:

- **Absolute positional embeddings:** add a learned/sinusoidal vector per position (original Transformer, GPT-2).
- **Rotary Position Embeddings (RoPE):** rotate Q/K by an angle proportional to position — encodes **relative** position and extrapolates better to longer contexts (Llama, many modern models).
- **ALiBi:** adds a distance-based bias to attention scores.

The choice matters for **context-length extension** — techniques like RoPE scaling let models handle longer inputs than they were trained on.

---

## 7) The context window & the quadratic cost

The **context window** is the maximum number of tokens (prompt + generated) the model can attend to at once — e.g. 8K, 128K, or 1M+ in recent Claude/GPT models. It bounds how much conversation, document, or code the model can "see."

Attention compares every token with every other token, so compute and memory for the attention scores scale as:

```
cost ∝ (sequence length)²        ← the quadratic bottleneck
```

This is **the** reason long contexts are expensive and why tokenization efficiency (note `01`) matters. Mitigations:

- **FlashAttention:** IO-aware exact attention that avoids materializing the full `L×L` score matrix → big speed/memory wins.
- **GQA/MQA:** shrink the KV cache read at inference.
- **Sparse / sliding-window / linear attention:** approximate attention to break the `O(L²)` scaling.
- **RoPE scaling / long-context training:** push usable context to 128K–1M tokens.

---

## 8) End-to-end flow through one block

```
For a token vector x at position i:
1. LayerNorm(x)
2. Attention:
     q = W_Q·x ;  for all j≤i:  k_j = W_K·x_j ,  v_j = W_V·x_j
     scores = (q·k_jᵀ)/√d_k   →  causal mask  →  softmax  →  weights
     a = Σ_j weight_j · v_j         (multi-head: do this h× and concat → W_O)
3. x = x + a                        (residual)
4. LayerNorm(x)
5. f = W₂ · GELU(W₁ · x)            (feed-forward)
6. x = x + f                        (residual)
→ pass x to the next block; after the last block, LM head → logits (note 01 §7)
```

Repeat for `N` blocks. The final position's vector, after the top block, is projected by the LM head into next-token logits.

---

## 9) Reliability / scaling / operations lens

- **Depth & width scale predictably:** more layers (`N`), wider `d_model`, more heads → more parameters → lower loss (scaling laws, note `03`). The architecture is intentionally simple and uniform so it **scales cleanly** across thousands of GPUs.
- **The attention KV state is the runtime bottleneck** (note `05`): it grows with context length and dominates inference memory/bandwidth.
- **What to watch when training:** loss spikes/divergence (mitigated by pre-norm, careful init, gradient clipping, lower learning rates), numerical stability in low precision (note `03`), and dead/saturated activations.
- **Failure modes of attention:** long-context "lost in the middle" (models under-attend to mid-context tokens), and degraded quality when context is extended far beyond training length.

---

## 10) Key takeaways

- ChatGPT/Claude are **decoder-only Transformers**: `N` blocks of **self-attention + feed-forward**, wrapped in **residuals + layer norm**.
- **Attention** is a content-based lookup using **Query/Key/Value**: `softmax(QKᵀ/√d_k)·V`; a **causal mask** keeps it from seeing the future.
- **Multi-head** attention learns many relationship types in parallel; **GQA/MQA** shrink K/V for cheaper inference.
- The **FFN/MLP** does per-token computation and stores much of the model's "knowledge."
- **Positional encodings** (RoPE, absolute) inject order; attention alone is order-blind.
- Attention is **O(L²)** in sequence length → the source of the **context-window** cost; FlashAttention/GQA/sparse attention mitigate it.

---

## 11) Quick glossary

- **Decoder-only:** architecture that only predicts the next token (no separate encoder); used by GPT/Claude/Llama.
- **Q / K / V:** query, key, value vectors computed per token via learned projections.
- **Attention head:** one Q/K/V attention operation; multi-head runs many in parallel.
- **Causal mask:** blocks attention to future tokens.
- **FFN / MLP:** per-token 2-layer network (~4× hidden), stores knowledge.
- **Residual stream:** the running `x + sublayer(x)` vector threaded through all blocks.
- **RoPE:** rotary positional embedding encoding relative position.
- **Context window:** max tokens the model can attend to at once.
- **FlashAttention:** IO-aware exact-attention kernel that avoids the full L×L matrix.
- **GQA / MQA:** grouped/multi-query attention that shares K/V to shrink the KV cache.

---

## 12) Sources & further reading

**Primary source (this series)**
- Stanford CS229 — *Building Large Language Models (LLMs)*: <https://youtu.be/9vM4p9NN0Ts>

**Foundational papers**
- Vaswani et al., *Attention Is All You Need*: <https://arxiv.org/abs/1706.03762>
- Su et al., *RoFormer: Rotary Position Embedding (RoPE)*: <https://arxiv.org/abs/2104.09864>
- Press et al., *ALiBi — Train Short, Test Long*: <https://arxiv.org/abs/2108.12409>
- Shazeer, *Fast Transformer Decoding (Multi-Query Attention)*: <https://arxiv.org/abs/1911.02150>
- Ainslie et al., *GQA — Grouped-Query Attention*: <https://arxiv.org/abs/2305.13245>
- Dao et al., *FlashAttention*: <https://arxiv.org/abs/2205.14135>

**Explainers**
- Jay Alammar, *The Illustrated Transformer*: <https://jalammar.github.io/illustrated-transformer/>
- Andrej Karpathy, *Let's build GPT from scratch*: <https://www.youtube.com/watch?v=kCc8FmEb1nY>
- Anthropic (Transformer Circuits), *A Mathematical Framework for Transformer Circuits*: <https://transformer-circuits.pub/2021/framework/index.html>
- Lilian Weng, *The Transformer Family*: <https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/>
