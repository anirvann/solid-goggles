# Inference, Serving & the ChatGPT/Claude Product — Detailed Notes

> Companion deep-dive for the summary diagram: `llm-inference-serving-chat-product-sketchbook.png`.
> The image is the quick summary; this document is the detailed reference.

**Learning goal:** Trace what actually happens when you press **Enter** in ChatGPT or Claude: how the request is assembled (**system prompt + conversation history**), how tokens are **generated** (decoding strategies, the **prefill vs decode** phases, the **KV cache**), why generation is **memory-bound**, and how the product layer adds **streaming, context management, tools/function-calling, retrieval (RAG), multimodality, and safety**. This connects the model (notes `01`–`04`) to the assistant experience.

> The engine is a next-token predictor; the *product* is everything wrapped around it to make that engine feel like a knowledgeable, safe collaborator.

---

## 1) From "the model" to "the assistant": what a chat turn really is

The model is **stateless** — it only ever sees a single flat sequence of tokens and predicts the next one. The **chat feeling** of memory and roles is an illusion created by the application, which **re-sends the whole conversation** every turn, formatted with role markers.

```
Assembled prompt each turn (conceptually):

[system]  You are Claude/ChatGPT. Be helpful, honest, harmless. Today is …  Tools: …
[user]    How do CDNs work?
[assistant] A CDN is a globally distributed cache …
[user]    And how is that different from a proxy?     ← newest user turn
[assistant] ▮                                          ← model generates from here
```

- **System prompt:** hidden instructions (persona, safety rules, date, available tools). Set by the product, not the user (note `04` §6).
- **Conversation history:** every prior user+assistant turn, resent so the model has "memory" — this is why long chats cost more and eventually hit the **context window** (note `02` §7).
- **Chat template / special tokens:** role boundaries are encoded with special tokens (e.g. `<|im_start|>`, `[INST]`) the model was post-trained to recognize.

---

## 2) The autoregressive serving loop

At its core, serving is the loop from note `01`, run until a stop condition:

```
context = system + history + user turn
loop:
    logits      = model(context)[last position]     # forward pass
    probs       = softmax(logits / temperature)
    next_token  = sample(probs, top_p, top_k)        # decoding strategy
    stream(next_token)                               # push to the UI
    context     = context + next_token
    if next_token == <eos> or len ≥ max_tokens: break
```

- Output appears **token-by-token** ("typing") because each token literally depends on the previous one — you're watching the loop iterate.
- **Total latency ≈ TTFT + (tokens × TPOT)** — time-to-first-token plus per-token time (defined in §5).

---

## 3) Decoding strategies — turning logits into the next token

The forward pass gives a probability over the whole vocabulary; the **decoding strategy** picks the actual token and controls the creativity/consistency trade-off.

| Strategy | Rule | Effect |
| --- | --- | --- |
| **Greedy** | Always take `argmax` | Deterministic; can be repetitive/bland |
| **Temperature `T`** | Scale logits `/T` before softmax | `T<1` sharper/safer, `T>1` more diverse, `T→0`≈greedy |
| **Top-k** | Sample only from the `k` most likely tokens | Caps the tail; fixed cutoff |
| **Top-p (nucleus)** | Sample from the smallest set with cumulative prob ≥ `p` | Adapts cutoff to the model's confidence |

- Real deployments usually combine **temperature + top-p** (e.g. `T≈0.7, p≈0.9`).
- **Extras:** repetition/frequency penalties (reduce loops), **stop sequences**, **max tokens**, and **logit bias** to ban/boost tokens.
- **Same prompt → different answers** is the direct result of sampling (note `01` §7). Set `T=0`/greedy for reproducibility.

---

## 4) Prefill vs decode + the KV cache (the two-phase reality)

Naively, generating token *n* would re-process all *n−1* previous tokens every step — `O(n²)` total. The **KV cache** avoids this by storing each token's attention **Key/Value** vectors so they're computed **once** and reused. Inference splits into two phases with very different performance profiles:

| Phase | Input | Work | Bottleneck | Scales with |
| --- | --- | --- | --- | --- |
| **Prefill** | Whole prompt at once | Process all prompt tokens in parallel; **build the KV cache**; emit 1st token | **Compute** (big matmuls) | Prompt length |
| **Decode** | 1 new token + cached K/V | One forward pass per token; new token's Q attends to **all cached K/V**; append its K/V | **Memory bandwidth** | Output length |

```
PREFILL (parallel, compute-bound)         DECODE (sequential, memory-bound)
 prompt ──▶ [ big forward pass ]           tok_i ─▶ [ forward pass (seq len 1) ]
        ──▶ fill KV cache ─▶ token₁         attends to KV cache ─▶ token_{i+1}
                                            append K/V ─▶ repeat …
```

**Why decode is memory-bound:** each step does tiny arithmetic (one new token) but must **read the entire model weights + the whole KV cache from GPU memory (HBM)**. At batch size 1 the GPU spends almost all its time *waiting on memory*, not computing — arithmetic intensity ≈ 1 FLOP/byte. This is the single most important fact about LLM inference cost.

**KV cache is the runtime bottleneck:** it grows **linearly with sequence length × batch size × layers** and can reach **gigabytes** for long contexts — often the limiter on how many requests fit on a GPU and how long the context can be.

---

## 5) Serving optimizations (how ChatGPT/Claude stay fast & cheap)

Because decode is memory-bound and the KV cache is huge, production systems (vLLM, TensorRT-LLM, TGI, etc.) apply:

- **Continuous batching:** dynamically pack many users' decode steps into one batch to **amortize weight reads** — the biggest throughput lever.
- **PagedAttention:** manage the KV cache in **paged blocks** (like OS virtual memory) to eliminate fragmentation and pack more concurrent sequences (vLLM).
- **GQA / MQA:** share K/V across heads to **shrink the KV cache** (note `02` §3).
- **FlashAttention:** IO-aware attention kernel cutting HBM traffic (notes `02`–`03`).
- **Quantization:** run weights (and even the KV cache) in **INT8/INT4/FP8** to cut bandwidth → faster decode.
- **Speculative decoding:** a small "draft" model proposes several tokens; the big model **verifies** them in one pass → multiple tokens per step.
- **Prefix/prompt caching:** reuse the KV cache for a shared prefix (e.g. a fixed system prompt) across requests → cheaper, faster TTFT.
- **Chunked prefill** for very long prompts so they don't block other users.

**Latency metrics that matter:** **TTFT** (time-to-first-token, dominated by prefill) and **TPOT/ITL** (time-per-output-token, dominated by decode). Streaming hides TPOT by showing tokens as they arrive.

---

## 6) Context window management

The context window (note `02` §7) is finite (8K → 1M tokens), so products actively manage what goes in:

- **Truncation / sliding window:** drop the oldest turns when the budget is exceeded.
- **Summarization / memory:** compress old history into a running summary; persist durable "memory" facts across sessions.
- **Retrieval (RAG):** fetch only the relevant chunks instead of stuffing everything (see §7).
- **"Lost in the middle":** models attend best to the **start and end** of context, so placement of key info matters.
- **Cost/latency:** every token in context is processed at prefill → long contexts raise both TTFT and $.

---

## 7) The product layer around the model

What makes ChatGPT/Claude *products* rather than a raw completion endpoint:

- **Tools / function calling:** the model emits a structured call (e.g. JSON) → the app runs a real function (web search, code execution, calculator, database, APIs) → result is fed back into context → the model continues. This is the backbone of **agents**.
- **Retrieval-Augmented Generation (RAG):** embed the query, search a **vector database** for relevant documents, and inject them into context so answers are **grounded** and **current** — reduces hallucination and adds private/fresh knowledge without retraining.
- **Multimodality:** images/audio/files are encoded into tokens/embeddings and prepended, so the same next-token engine can "see" and "hear."
- **Reasoning / "thinking" modes:** the model is trained/prompted to produce hidden chain-of-thought or run longer test-time compute before answering (o-series, Claude extended thinking).
- **Streaming (SSE):** tokens are pushed to the browser as generated for responsiveness.
- **Orchestration:** system-prompt injection, memory, rate limiting, retries, and multi-step agent loops all live here.

```
user turn ─▶ assemble(system + history + tools + retrieved docs)
          ─▶ MODEL ─▶ tool call? ──yes──▶ run tool ─▶ append result ─▶ MODEL …
                        └──no──▶ stream answer ─▶ safety check ─▶ user
```

---

## 8) Safety & moderation at serving time

Alignment (note `04`) is baked into weights, but products add **runtime guardrails**:

- **Input moderation:** classify/blocked disallowed requests before or alongside generation (e.g. OpenAI Moderation API).
- **Output filtering:** scan generated text for policy violations before it reaches the user; can stop/redact mid-stream.
- **System-prompt guardrails:** rules and refusal policies injected each turn.
- **Jailbreak/prompt-injection defense:** detect attempts to override the system prompt (especially critical once tools/RAG bring in untrusted external text).
- **Abuse controls:** rate limits, auth, logging, and usage policies.

---

## 9) End-to-end: pressing Enter in ChatGPT/Claude

```
1. You type a message in the chat UI.
2. App assembles the prompt: system prompt + full conversation history + your new turn
   (+ any tools schema, + retrieved/RAG docs, + attached images).
3. Input safety/moderation check.
4. PREFILL: model processes the whole prompt in parallel, builds the KV cache, emits token 1
   (prefix cache may skip re-computing a shared system prompt → faster TTFT).
5. DECODE loop: sample next token (temperature/top-p) → append K/V to cache → stream to UI …
      ├─ if the model emits a TOOL CALL: run the tool, feed the result back, keep decoding.
6. Stop on <eos> or max tokens; final output moderation.
7. The full turn (yours + the model's) is saved and re-sent as history on your next message.
```

**Risks/ops signals to watch:** TTFT & TPOT (latency SLOs), tokens/sec throughput, KV-cache memory pressure & evictions, context overflow/truncation, tool errors/timeouts, hallucination & grounding quality, jailbreak/prompt-injection attempts, and cost per conversation.

---

## 10) Key takeaways

- The model is **stateless**; the "conversation" is the app **re-sending system prompt + full history** as one token sequence every turn.
- Generation is the **autoregressive loop**: `logits → softmax(/temperature) → sample(top-p/top-k) → append → repeat`, streamed token-by-token.
- Inference has **two phases**: **prefill** (compute-bound, builds the KV cache) and **decode** (memory-bandwidth-bound, one token at a time). **Decode dominates and is memory-bound.**
- The **KV cache** makes generation `O(n)` instead of `O(n²)` but grows with context×batch and is the main serving bottleneck → **continuous batching, PagedAttention, GQA, quantization, speculative decoding, prefix caching**.
- The **product layer** — tools/function-calling, **RAG**, multimodality, reasoning modes, streaming, and **safety/moderation** — is what turns the raw next-token engine into ChatGPT/Claude.
- Watch **TTFT** and **TPOT**; manage the **context window** deliberately (truncate/summarize/retrieve).

---

## 11) Quick glossary

- **System prompt:** hidden instructions (role, rules, date, tools) prepended each turn.
- **Chat template:** special tokens marking user/assistant/system turns.
- **Prefill:** parallel pass over the prompt that builds the KV cache (compute-bound).
- **Decode:** sequential per-token generation reading the KV cache (memory-bound).
- **KV cache:** stored Key/Value vectors per token so attention isn't recomputed.
- **TTFT / TPOT:** time-to-first-token / time-per-output-token.
- **Continuous batching:** dynamically batching many requests' decode steps.
- **PagedAttention:** paged KV-cache memory management (vLLM).
- **Quantization:** lower-precision (INT8/INT4/FP8) weights/KV to cut bandwidth.
- **Speculative decoding:** draft model proposes, big model verifies → multi-token steps.
- **RAG:** retrieval-augmented generation — inject retrieved docs to ground answers.
- **Function calling / tools:** model emits structured calls the app executes.
- **Prompt injection:** malicious input that tries to override the system prompt.

---

## 12) Sources & further reading

**Primary source (this series)**
- Stanford CS229 — *Building Large Language Models (LLMs)*: <https://youtu.be/9vM4p9NN0Ts>

**Inference internals**
- Kwon et al., *Efficient Memory Management for LLM Serving (PagedAttention / vLLM)*: <https://arxiv.org/abs/2309.06180>
- Leviathan et al., *Fast Inference via Speculative Decoding*: <https://arxiv.org/abs/2211.17192>
- Pope et al., *Efficiently Scaling Transformer Inference*: <https://arxiv.org/abs/2211.05102>
- Liu et al., *Lost in the Middle: How LMs Use Long Contexts*: <https://arxiv.org/abs/2307.03172>
- Holtzman et al., *The Curious Case of Neural Text Degeneration (top-p / nucleus sampling)*: <https://arxiv.org/abs/1904.09751>
- HuggingFace, *How to generate text (decoding strategies)*: <https://huggingface.co/blog/how-to-generate>
- vLLM docs: <https://docs.vllm.ai/>

**Product layer: tools, RAG, safety**
- Lewis et al., *Retrieval-Augmented Generation (RAG)*: <https://arxiv.org/abs/2005.11401>
- OpenAI, *Function calling / tools guide*: <https://platform.openai.com/docs/guides/function-calling>
- Anthropic, *Tool use (function calling)*: <https://docs.anthropic.com/en/docs/build-with-claude/tool-use>
- Anthropic, *Contextual retrieval*: <https://www.anthropic.com/news/contextual-retrieval>
- OpenAI, *Moderation guide*: <https://platform.openai.com/docs/guides/moderation>
- OWASP, *Top 10 for LLM Applications (prompt injection, etc.)*: <https://owasp.org/www-project-top-10-for-large-language-model-applications/>
