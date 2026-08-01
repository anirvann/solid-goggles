# What an LLM Is & Next-Token Prediction — Detailed Notes

> Companion deep-dive for the summary diagram: `llm-next-token-prediction-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Build the correct mental model for what ChatGPT and Claude *are* under the hood — a neural network that models a **probability distribution over token sequences** and generates text by repeatedly predicting the **next token**. Understand the full input→output path: **tokenize → embed → transformer → logits → softmax → sample → append → repeat**.

> Primary source for this series: Stanford **CS229 — "Building Large Language Models (LLMs)"** (Yann Dubois): <https://youtu.be/9vM4p9NN0Ts>. This note maps to the lecture's "language modeling", "tokenization", and "next-token pipeline" segments.

---

## 1) The one-sentence mental model

An LLM is an **autocomplete engine trained on a huge fraction of the internet**. Given some text, it predicts what token most plausibly comes next, appends it, and repeats. ChatGPT and Claude are this same engine wrapped with **post-training** (to behave like a helpful assistant) and a **serving system** (chat UI, context handling, tools, safety).

- It is **not** a database of facts and it is **not** running a search query. It is a statistical model of *"what text usually follows this text"*.
- Its apparent knowledge, reasoning, and style are all **side effects** of getting extremely good at next-token prediction over trillions of tokens.

```
"The capital of France is" ──▶ [ LLM ] ──▶ "Paris"   (highest-probability next token)
```

---

## 2) A language model = a probability distribution over sequences

Formally, a language model assigns a probability to any sequence of tokens `x₁ … x_L`:

- **Plausible / grammatical / true** text → **high** probability.
- **Nonsensical / ungrammatical / false** text → **low** probability.

Because probabilities of a full sentence are hard to model directly, autoregressive (AR) models use the **chain rule of probability** to factor the joint into a product of next-token conditionals:

```
P(x₁, x₂, …, x_L) = ∏(i=1…L) P(xᵢ | x₁ … x_{i-1})
                  = P(x₁)·P(x₂|x₁)·P(x₃|x₁x₂)· … ·P(x_L | x₁…x_{L-1})
```

- Every factor `P(xᵢ | x_<i)` is exactly **"predict the next token given everything so far."**
- This factorization is **exact** (no approximation) — it is just the chain rule.
- **Generative modeling:** once the model approximates this distribution well, you can **sample** from it to produce new, human-like text.

> Key idea from the lecture: modeling the sequence distribution and *generating* text are two sides of the same coin. Learn the distribution → you can draw samples from it.

---

## 3) The next-token prediction pipeline (train + infer)

Every forward pass of ChatGPT/Claude follows the same six steps:

| # | Step | What happens | Output shape (per token) |
| --- | --- | --- | --- |
| 1 | **Tokenize** | Split raw text into subword **tokens**, map each to an integer ID | token IDs |
| 2 | **Embed** | Look up a learned **vector** for each token ID (+ position info) | `d_model` vector |
| 3 | **Transformer** | Stack of attention + feed-forward layers builds **context-aware** representations | `d_model` vector |
| 4 | **Unembed (LM head)** | Linear projection to **one logit per vocabulary token** | `|V|` logits |
| 5 | **Softmax** | Convert logits → a **probability distribution** over the whole vocabulary | `|V|` probabilities |
| 6 | **Sample / pick** | Choose the next token (greedy or sampling), append, and loop | 1 token |

```
text ─▶ [tokenize] ─▶ IDs ─▶ [embed] ─▶ vectors ─▶ [Transformer ×N]
     ─▶ hidden state ─▶ [LM head] ─▶ logits ─▶ [softmax] ─▶ probabilities
     ─▶ [sample] ─▶ next token ─┐
        ▲                       │
        └───────── append ──────┘   (autoregressive loop)
```

- **Training** stops at step 5 conceptually: it compares the predicted distribution against the *actual* next token and updates weights. It does **not** need to sample/detokenize, because the true next token is the supervision signal (see §6).
- **Inference** runs all six steps and loops (steps 4–6 covered in note `05`).

---

## 4) Tokenization — turning text into numbers

Neural nets operate on numbers, so text must be chopped into a fixed **vocabulary** of units called **tokens**. The final layer of the model has exactly one output per vocabulary entry, so the **vocabulary size directly sets the model's output dimension** — tokenization is a consequential design choice, not a detail.

### Why not just use words, or just characters?

| Scheme | Pros | Cons |
| --- | --- | --- |
| **Words** | Intuitive, short sequences | Huge/unbounded vocab; breaks on typos, rare words, and languages without spaces (Chinese, Japanese) |
| **Characters** | Tiny vocab, handles *anything* | Very **long** sequences → expensive, since Transformer attention cost grows **~quadratically** with sequence length |
| **Subword (BPE)** ✅ | Balance of both; ~3–4 chars/token on average; robust to rare words | Still awkward for long numbers, whitespace-heavy code |

Modern LLMs use **subword tokenization**, most commonly **Byte-Pair Encoding (BPE)**.

### How BPE works (training the tokenizer)

1. Start with the vocabulary = **individual characters (or bytes)**.
2. Scan the corpus and find the **most frequent adjacent pair** of tokens.
3. **Merge** that pair into a new single token; add it to the vocabulary.
4. **Repeat** thousands of times, growing subword units (e.g. `e`,`s` → `es`; `low`,`est` → `lowest`).

The result: common words become **one token**, rare words split into **several subword tokens**, and truly novel strings fall back to characters/bytes. Keeping the small units means the tokenizer is **robust** — it can encode anything, including typos.

- A **pre-tokenizer** first splits on spaces/punctuation so merges stay sensible.
- **Rule of thumb:** ~4 characters ≈ 1 token ≈ ~0.75 English words. "This is amazing" ≈ 3–4 tokens.
- **Known weak spots:** arithmetic on long numbers (digits split unevenly), rigid code formatting, and rare Unicode — all consequences of how the vocabulary was built.

---

## 5) Embeddings — giving tokens meaning

A token ID like `1917` carries no meaning on its own. The **embedding layer** is a learned lookup table mapping each ID to a dense vector of size `d_model` (e.g. 4096). During training these vectors organize so that **tokens used in similar contexts land near each other** in vector space (the classic "king − man + woman ≈ queen" intuition).

- **Token embedding:** *what* the token is.
- **Positional information:** *where* it sits in the sequence — attention is order-agnostic by itself, so position must be injected (learned positional embeddings, or rotary/RoPE; detailed in note `02`).
- The Transformer's job (note `02`) is to turn these static per-token vectors into **context-aware** representations, so the vector for "bank" differs in "river bank" vs "bank account."

---

## 6) The training objective — cross-entropy / next-token loss

Pretraining is **self-supervised**: the "label" for each position is simply the **actual next token** in the text — no human annotation required. This is why the entire internet can be used as training data.

- The model outputs a probability distribution `P(· | x_<i)` at every position.
- The loss is **cross-entropy** against the one-hot true next token — equivalently, **maximize the log-likelihood** of the real text:

```
Loss = − (1/L) · Σ(i=1…L) log P(xᵢ_true | x₁ … x_{i-1})
```

- Minimizing cross-entropy = making the true continuations more probable.
- To predict the next word well over *all* of human text, the model is forced to implicitly learn **grammar, facts, style, some reasoning, and world knowledge** — capabilities emerge as a by-product of compression. (Loss curves, perplexity, and scaling are covered in note `03`.)

---

## 7) From logits to a token — softmax & sampling (intro)

The LM head produces one **logit** (raw score) per vocabulary token. **Softmax** turns logits into a proper probability distribution:

```
P(token k) = exp(logit_k / T) / Σⱼ exp(logit_j / T)
```

- **Temperature `T`** rescales logits *before* softmax: `T<1` sharpens (more deterministic), `T>1` flattens (more random/creative), `T→0` ≈ greedy.
- Then a **decoding strategy** picks the actual token: **greedy**, **top-k**, or **top-p (nucleus)** sampling.
- This is the knob that makes the same prompt produce different answers on different runs. Full treatment of decoding, KV cache, and the autoregressive serving loop is in note `05`.

---

## 8) End-to-end mini example

Prompt: `"The capital of France is"`

```
1. tokenize   → ["The"," capital"," of"," France"," is"]  → [464, 3139, 286, 4881, 318]
2. embed      → 5 vectors (+ positions)
3. transformer→ contextual hidden states (last position summarizes the whole prompt)
4. LM head    → logits over the full vocabulary (~100k entries)
5. softmax    → P(" Paris")=0.86, P(" the")=0.04, P(" a")=0.03, …
6. sample     → " Paris"  →  append  →  feed back in  →  predict next token …
```

Repeat until an **end-of-sequence** token is produced or a length limit is hit. That loop — one token at a time — is literally what you see when ChatGPT/Claude "type" their answer.

---

## 9) Where ChatGPT & Claude fit

Everything above describes a **base (pretrained) model** — a raw next-token predictor. A base model will happily continue your prompt, but it does **not** reliably act like a helpful, safe assistant. Turning it into ChatGPT or Claude requires two more ingredients:

- **Post-training / alignment** (note `04`): SFT + RLHF (ChatGPT) and Constitutional AI / RLAIF (Claude) reshape the distribution toward *helpful, honest, harmless* assistant behavior.
- **A serving product** (note `05`): the chat interface assembles a **system prompt + conversation history**, runs the autoregressive loop, streams tokens, and adds tools, retrieval, and safety filters.

The engine (this note) never changes — post-training and serving are layered on top.

---

## 10) Key takeaways

- An LLM is a **probability distribution over token sequences**, trained to **predict the next token** via the chain rule of probability.
- The pipeline is always **tokenize → embed → transformer → logits → softmax → sample → repeat** (autoregressive).
- **Tokenization** (usually **BPE subwords**) trades sequence length vs vocabulary size; vocab size = the model's output dimension.
- Training is **self-supervised** with **cross-entropy** loss — the label is just the real next token, so unlabeled internet text works. Knowledge/skills **emerge** from doing this at scale.
- **Softmax + temperature/sampling** convert scores into the actual token; this is the randomness knob.
- **ChatGPT and Claude = this engine + post-training + a serving system** — not a search engine or a fact database.

---

## 11) Quick glossary

- **Token:** a subword unit (~4 chars) that is the atomic input/output of the model.
- **Vocabulary (|V|):** the fixed set of tokens; sets the output layer width (~50k–200k today).
- **BPE (Byte-Pair Encoding):** tokenizer trained by iteratively merging the most frequent adjacent token pairs.
- **Embedding:** learned vector representing a token (and its position).
- **Autoregressive (AR):** generates one token at a time, each conditioned on all previous tokens.
- **Logits:** raw pre-softmax scores, one per vocabulary token.
- **Softmax:** turns logits into a probability distribution.
- **Cross-entropy loss:** training objective; penalizes low probability on the true next token.
- **Temperature:** scalar that sharpens/flattens the next-token distribution.
- **Base model:** a pretrained next-token predictor before alignment.

---

## 12) Sources & further reading

**Primary source (this series)**
- Stanford CS229 — *Building Large Language Models (LLMs)* (Yann Dubois): <https://youtu.be/9vM4p9NN0Ts>

**Foundational papers**
- Vaswani et al., *Attention Is All You Need* (Transformer): <https://arxiv.org/abs/1706.03762>
- Radford et al., *Language Models are Unsupervised Multitask Learners* (GPT-2): <https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf>
- Brown et al., *Language Models are Few-Shot Learners* (GPT-3): <https://arxiv.org/abs/2005.14165>
- Sennrich et al., *Neural Machine Translation of Rare Words with Subword Units* (BPE): <https://arxiv.org/abs/1508.07909>

**Explainers**
- Jay Alammar, *The Illustrated Transformer*: <https://jalammar.github.io/illustrated-transformer/>
- Jay Alammar, *The Illustrated GPT-2*: <https://jalammar.github.io/illustrated-gpt2/>
- OpenAI Tokenizer (see BPE in action): <https://platform.openai.com/tokenizer>
- Andrej Karpathy, *Let's build the GPT Tokenizer*: <https://www.youtube.com/watch?v=zduSFxRajkE>
- Anthropic, *Introduction to Claude* (what a model/assistant is): <https://docs.anthropic.com/en/docs/intro-to-claude>
