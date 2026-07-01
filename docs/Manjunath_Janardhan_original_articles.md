PART 1 ----
A step-by-step guide to driving Claude Code entirely offline on Apple Silicon — no cloud, no API bill, ~19 GB of RAM, and real-time decode speeds thanks to MLX and block-diffusion speculative decoding.
TL;DR — You can point Claude Code at a local Qwen 3.6 27-billion-parameter coding model running on your Mac. The trick is two pieces: `dflash serve` (an OpenAI-compatible MLX server that runs a 4-bit Qwen3.6–27B with DFlash speculative decoding) and `claude-code-router` (a bridge that translates Claude Code’s Anthropic API into OpenAI calls, tool calls included). End result: ~65 tok/s average (up to ~120 on cached turns), ~19 GB resident, fully offline. This post walks you through it end to end.
Part 1 of a two-part series. This post is the offline setup; [Part 2] benchmarks it head-to-head against a sparse mixture-of-experts model — and the result flips a common assumption about what makes local coding fast.
See it in action— 3 min 33 sec clip at 6× speed (a real 21-minute session): Claude Code driven entirely by the local 27B — three quick coding tasks, then a full FastAPI + React app built and run end to end. The long pause near the end is the ~4-minute context-explosion stall I dissect later in this post.

“6× speed (21-min session)”. three quick coding tasks, then a full FastAPI + React app built and run end to end
Why run Claude Code on a local model?
Claude Code is one of the best agentic coding tools available — but every request goes to the cloud, every token costs money, and nothing works on a plane. For experimentation, offline work, and privacy-sensitive code, it’s genuinely useful to drive the same Claude Code CLI against a model running on your own machine.
The catch has always been speed. A 27B model decoding at 8 tok/s makes an agent loop unusable — Claude Code fires lots of short, tool-heavy turns, and you feel every one. The fix is DFlash speculative decoding, which gets a 4-bit Qwen3.6–27B to ~65 tok/s average and up to ~120 tok/s on an Apple Silicon Mac. At that speed, a local 27B becomes a perfectly pleasant daily coding companion.
This guide shows you exactly how to wire it up.
What you’ll build
Three moving parts:
1. The model server — `dflash serve` loads the 4-bit Qwen3.6–27B target plus a tiny 2B draft model and exposes an OpenAI-compatible endpoint.
2. The bridge — `claude-code-router` (CCR) sits in front and translates Claude Code’s Anthropic-format requests into OpenAI-format calls, and translates the responses (text and tool calls) back.
3. Claude Code itself — launched via `ccr code`, talking to the bridge instead of the cloud.
How DFlash makes a 27B fast (the 30-second version)
DFlash( https://arxiv.org/abs/2602.06036 ) is lossless speculative decoding. A small draft model proposes a block of γ tokens; the big target model verifies the whole block in a single forward pass; accepted tokens are kept, the first rejected one is corrected. Because verification is one batched forward instead of γ sequential ones, you get a big throughput win with identical output quality to running the target alone.
The 2B draft (`z-lab/Qwen3.6–27B-DFlash`) is not a standalone model — it’s a purpose-built companion to the full Qwen3.6–27B, so acceptance rates are high (80–94% in practice, ~5.9 tokens accepted per cycle).
Why 4-bit MLX (and not a custom 3-bit quant)
I spent a while trying to beat this with a 3-bit codebook quant (TurboQuant) plus a hand-written verify kernel. It lost — and the reason is instructive.
Acceptance and tokens-per-cycle are basically identical — the draft proposes equally well against either target. The entire ~38× throughput gap is the verify path. MLX runs the hot loop with `mx.async_eval`, so the memory-bound weight materialization of a native int4 matmul overlaps with the draft’s compute and hides. A monolithic custom kernel sits squarely on the critical path and can’t overlap, so it regresses end-to-end even though it wins in isolation.
The lesson: on Apple Silicon with MLX, lean on the native int4 path and let async eval overlap the work. Custom quantization earns its keep for fitting models that wouldn’t otherwise load — not for squeezing a model that already fits.
Prerequisites
- macOS on Apple Silicon(M-series), with ≥ ~24 GB free RAM (≈16 GB target + ≈3.5 GB draft + KV cache). Comfortable on 32–64 GB.
- Python with `dflash-mlx`( https://pypi.org/project/dflash-mlx ) installed: `pip install dflash-mlx` (ideally in a venv).
- Node ≥ 18, then `npm i -g @musistudio/claude-code-router` (this guide uses CCR 2.0.0).
- Claude Code CLI (`claude`) on your `PATH`.
- The models cached locally (they’ll auto-download on first run): `mlx-community/Qwen3.6–27B-4bit` and `z-lab/Qwen3.6–27B-DFlash`.
Step 1 — Start the OpenAI-compatible model server
dflash serve \
 --model mlx-community/Qwen3.6–27B-4bit \
 --draft-model z-lab/Qwen3.6–27B-DFlash \
 --host 127.0.0.1 -port 8787 \
 --verify-mode adaptive \
 --max-tokens 2048 \
 --chat-template-args '{"enable_thinking": false}'
Two flags matter:
- ` — verify-mode adaptive` shortens the verify block automatically when acceptance drops, which maximizes throughput across mixed prompts.
- ` — chat-template-args ‘{“enable_thinking”: false}’` turns OFF Qwen3.6’s `<think>` reasoning mode. This is important for Claude Code. With thinking on, the model emits a `reasoning_content` block and burns latency and tokens before it acts — bad for an agent loop. Off → direct content and crisp tool calls. (Want chain-of-thought back? Just drop the flag.)
Sanity check it:
curl -s localhost:8787/v1/chat/completions -d '{"model":"mlx-community/Qwen3.6–27B-4bit","messages":[{"role":"user","content":"Reply with exactly: dflash works"}],"max_tokens":64,"temperature":0}'
# -> "dflash works"
# server log shows e.g. "decode 121.4 tok/s | 93.8% accepted"
The first request is slow— that’s kernel warm-up plus prompt prefill. Every request after that decodes fast.
Step 2 — Configure the bridge (claude-code-router)
Create `~/.claude-code-router/config.json`:
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "Providers": [
    {
      "name": "dflash",
      "api_base_url": "http://127.0.0.1:8787/v1/chat/completions",
      "api_key": "dflash-local",
      "models": ["mlx-community/Qwen3.6–27B-4bit"],
      "transformer": { "use": [ ["maxtoken", { "max_tokens": 8192 }], "enhancetool" ] }
    }
  ],
  "Router": {
  "default": "dflash,mlx-community/Qwen3.6–27B-4bit",
  "background": "dflash,mlx-community/Qwen3.6–27B-4bit",
  "think": "dflash,mlx-community/Qwen3.6–27B-4bit",
  "longContext": "dflash,mlx-community/Qwen3.6–27B-4bit",
  "longContextThreshold": 30000,
  "webSearch": "dflash,mlx-community/Qwen3.6–27B-4bit"
  }
}
What the pieces do:
- `enhancetool` transformer— hardens tool-call formatting for a non-Claude model. This matters because Claude Code is *extremely* tool-heavy; `enhancetool` is what makes a tool request come back as a proper Anthropic `tool_use` block instead of malformed text.
- `maxtoken`— caps the response length the model/server will emit.
- All routes → one model — we only serve a single model, so `default`, `background`, `think`, `longContext`, and `webSearch` all point at it. Even Claude Code’s lightweight `background` tasks hit the 27B, which is fine locally.
Then load the config:
ccr restart # picks up the config; bridge runs on :3456
ccr status
Step 3 — Launch Claude Code on the local model
ccr code # interactive Claude Code, driven by the local 27B
OR
ccr code -p "…" # headless one-shot
Verify the whole chain end to end:
ccr code -p "Reply with exactly the three words: local model online" - output-format text
# -> local model online
That’s it — Claude Code is now running entirely against a model on your Mac. Tool use works too: a `POST :3456/v1/messages` returns a `text` block for prose and a `tool_use` block for tool requests, exactly like the cloud API.
One-command bring-up
Once it works, wrap startup in a tiny idempotent script so you don’t retype the commands. It checks whether `dflash serve` is already on `:8787`, starts it via `nohup` if not, restarts CCR, and prints the launch instructions:
#!/usr/bin/env bash
set -euo pipefail
SERVE_PORT=8787
TARGET="mlx-community/Qwen3.6–27B-4bit"
DRAFT="z-lab/Qwen3.6–27B-DFlash"
if ! curl -s -o /dev/null -m 2 "http://127.0.0.1:${SERVE_PORT}/v1/models"; then
  nohup dflash serve \
 --model "${TARGET}" --draft-model "${DRAFT}" \
 --host 127.0.0.1 -port "${SERVE_PORT}" \
 --verify-mode adaptive --max-tokens 2048 \
 --chat-template-args '{"enable_thinking": false}' \
> /tmp/dflash_serve.log 2>&1 &

for _ in $(seq 1 60); do
  curl -s -o /dev/null -m 2 "http://127.0.0.1:${SERVE_PORT}/v1/models" && break
sleep 2
done

fi

ccr restart || ccr start
echo "Ready -> run: ccr code"
Tear down: `ccr stop` and `pkill -f “dflash serve”`.
One thing worth knowing: CCR runs as its own daemon and survives your terminal, but a `dflash serve` you started inside a Claude Code session dies with that session. The `nohup` launcher above gives you a persistent server.
Performance: what to actually expect
- Decode speed: ~65 tok/s average across mixed prompts; up to ~120 tok/s on cached/coding turns (prefix-cache hits).
- Acceptance: ~80–94%, around 5.9 tokens accepted per verify cycle.
- Memory: ~19 GB resident total — ~16 GB target + ~3.5 GB draft + KV/prefix cache. The server prints its caps at startup (e.g. wired ~52 GB, prefix cache 8 GB).
- Quality: identical to running the 4-bit Qwen3.6–27B without DFlash — speculative decoding is lossless.
A genuinely capable coding model, fully local, at interactive speed, on a laptop.
Why it’s actually fast — and the one thing that will stall it
Here’s a number that should worry you: Claude Code’s baseline prompt — system instructions, tool definitions, your `CLAUDE.md` — is already ~24,000 tokens before you type anything. A 27B prefills at ~150–220 tok/s on this Mac, so prefilling 24k tokens from scratch takes ~2 minutes. If every turn paid that, the agent loop would be unusable.
It isn’t, because of DFlash’s prefix cache. After the first turn, the server snapshots the KV state for that 24k prefix, and every subsequent turn only prefills the new tokens (your message + the latest tool results). In my own testing the cache “restored” prefill at 8,000–30,000 tok/s, so 24–35k-token turns came back in 2–8 seconds. The prefix cache is the unsung hero that makes a local agent viable at all.
But the cache has a cliff. When the prefix diverges (something early in the conversation changes) or gets evicted (the in-memory cache holds a limited number of entries), you fall back to a full prefill — and the cost is now `O(context)`.
I hit this hard while recording the demo for this very post. I asked the local 27B to build and run a full-stack FastAPI + React calculator app. It did — beautifully. Then I asked it to stop the two dev servers… and it went silent for four minutes. (That’s the long pause near the end of the demo video above.)
It hadn’t crashed. By that point the conversation had ballooned to 35,129 tokens — every file it wrote, every tool result, plus the running servers’ console output. That “stop the servers” turn was a cache miss, so the model re-prefilled all 35k tokens at ~143 tok/s ≈ 245 seconds before it could emit a single token. (Memory was fine the whole time — ~21 GB peak. It was pure prefill.) The fix was instant: `/clear` reset the context to a few hundred tokens, and the next turn responded in 3 seconds.
Two operational lessons that will save you the same stall:
- `/clear` (or start a fresh session) before an unrelated request. Asking a 35k-token coding conversation to “stop the servers” makes it re-read 35k tokens first. A clean context answers instantly.
- Don’t build and run a big app in one session. Long-lived dev-server output floods the context faster than anything else.
This raises an obvious question: if prefill is the real cost, is a dense 27B even the right model for local agentic coding? I benchmarked exactly that — see Part 2.
Sparse MoE vs Speculative Decoding: The Fastest Way to Run a Local Coding LLM on Apple Silicon
I benchmarked three ways to run a local agentic coding assistant on a Mac. The mixture-of-experts model reached the…
medium.com
Honest caveats
- It’s a 27B, not Claude. Set expectations: weaker multi-step agentic reasoning, more tool-call mistakes, occasional format drift versus the real cloud Claude Code experience. `enhancetool` and thinking-off mitigate this, but they don’t close the gap.
- Thinking-off is a deliberate trade. You’re trading raw chain-of-thought reasoning for speed and tool reliability. Toggle it per-task via the chat-template arg.
One model serves every route. If trivial `background` tasks feel sluggish, `ccr ui` lets you wire a separate small model just for those.
Press enter or click to view image in full size

ccr ui. Image By Manjunath Janardhan
Switching models means restarting the server. `dflash serve` loads one target at a time.
FAQ
Does this work on an Intel Mac or a non-Mac?
No. MLX and these int4 kernels are Apple Silicon only. On other hardware you’d use a different backend (e.g. llama.cpp or vLLM) behind the same claude-code-router bridge.
Will it fit in 16 GB?
It’s tight. ~19 GB resident is the realistic floor with the draft and KV cache. 24 GB is workable, 32–64 GB is comfortable.
Is the output quality degraded by speculative decoding?
No. DFlash is lossless — the target model verifies every block, so you get exactly what the 4-bit model would produce on its own, just faster. The only quality reduction is from 4-bit quantization itself, which is mild.
Can I use this with Cursor or VS Code instead?
The same `dflash serve` + `claude-code-router` stack exposes a standard OpenAI endpoint, so any tool that accepts a custom base URL can point at it. This guide focuses on the Claude Code CLI.
Why claude-code-router and not just point Claude Code at the server?
Claude Code speaks the Anthropic Messages API; `dflash serve` speaks OpenAI Chat Completions. CCR translates between them — including the bidirectional tool-call format, which is the hard part.
Conclusion
With two open-source pieces — `dflash-mlx` for fast lossless speculative decoding and `claude-code-router` for the API bridge — you can run Claude Code against a 4-bit Qwen3.6–27B entirely on a Mac, at ~65 tok/s and ~19 GB of RAM. It won’t replace Cloud Claude for hard agentic work, but it’s a fast, free, offline coding model that’s a good use case for IP-related code.
Next up — Part 2: DFlash makes this 27B decode fast. But is decoding even the bottleneck for agentic coding? I benchmarked this exact setup against a sparse mixture-of-experts (MoE) model and a pla in dense model, at context lengths from 2K to 24K. The result flipped my assumptions — and pointed at a simpler, bigger speedup than speculative decoding. → [Sparse MoE vs Speculative Decoding: The Fastest Way to Run a Local Coding LLM on Apple Silicon]
Sparse MoE vs Speculative Decoding: The Fastest Way to Run a Local Coding LLM on Apple Silicon
I benchmarked three ways to run a local agentic coding assistant on a Mac. The mixture-of-experts model reached the…
medium.com
Resources
DFlash project page (Z Lab)
https://z-lab.ai/projects/dflash/
DFlash reference implementation on GitHub:
https://github.com/z-lab/dflash
mlx-community/Qwen3.6–27B-4bit on Hugging Face
https://huggingface.co/mlx-community/Qwen3.6-27B-4bit
Draft — z-lab/Qwen3.6–27B-DFlash on Hugging Face
https://huggingface.co/z-lab/Qwen3.6-27B-DFlash

PART 2 ----

I benchmarked three ways to run a local agentic coding assistant on a Mac. The mixture-of-experts model reached the first token up to 6× faster than the alternatives — and it has nothing to do with the trick everyone reaches for first.
I wired up Claude Code to run entirely on a local 4-bit Qwen3.6–27B with DFlash speculative decoding. This is what happened when I tried to make it faster.
In Part 1, I got Claude Code running offline against a 4-bit Qwen3.6–27B on my Mac, using DFlash speculative decoding to push token generation to ~65 tok/s. It felt fast. So I went for the next speedup — and discovered I’d been optimizing the wrong half of the problem.
If you run a coding assistant like Claude Code, Aider, or Cursor against a local LLM on Apple Silicon, you’ve felt the lag: you send a message, and the model just… sits there before a single token appears. The instinct is to reach for speculative decoding to fix it — exactly what Part 1 did.
So I tested that instinct properly. On an Apple Silicon Mac (M4, 64 GB unified memory), I ran the same agentic coding workload three ways and measured every turn. The result was the opposite of what I expected — and it points to a much simpler lever than spec-decode.
TL;DR — Local agentic coding is prefill-bound, not decode-bound. A sparse mixture-of-experts (MoE) model reaches first token up to 6.3× faster than a dense model and 4.5× faster than dense + speculative decoding at a realistic 24k-token context. Speculative decoding makes token generation 2–3× faster — but generation isn’t the bottleneck, so it loses where it counts.
Why local agentic coding is prefill-bound
Two phases decide how fast an LLM feels:
- Prefill — the model reads your prompt and produces the first token. Cost scales with prompt length (time-to-first-token, TTFT).
- Decode — the model generates each subsequent token, one at a time.
For a chatbot, you type a short question and read a long answer, so decode dominates. Agentic coding is the mirror image. Tools like Claude Code stuff the system prompt, tool definitions, file contents, and conversation history into every single turn — easily 18,000–25,000 tokens — and the model often replies with a short tool call. So the cost is almost entirely prefill, paid again on every turn.
This matters because speculative decoding only accelerates decode. It drafts several tokens with a small model and verifies them in one pass with the big one. If your bottleneck is reading a 24k-token prompt, spec-decode is optimizing the wrong half.
The three contenders
All three are Qwen3.6-family models, quantized to run comfortably in 64 GB, served behind an OpenAI-compatible endpoint:
The setup
I deliberately bypassed the agent loop for measurement. Instead of driving Claude Code by hand — noisy and impossible to reproduce — I hit each server’s `/v1/chat/completions` endpoint directly with a small harness that streams the response and records TTFT-based prefill tok/s, decode tok/s, and per-turn latency.
Two modes:
1. Task mode — the goal ”build a full-stack FastAPI + React calculator” split into three small, focused sub-prompts (backend, component, wiring), each sent as a fresh single-turn request. This mimics good prompt hygiene: short, `/clear`’d turns.
2. Sweep mode — a realistic agentic system preamble padded to 2k / 8k / 16k / 24k tokens, then a tiny question. This isolates the prefill-vs-context curve— the thing that actually hurts in agentic coding.
The two TurboQuant models were served with `turboquant-serve` (3-bit weights + 8-bit-key / 3-bit-value KV-cache quantization). The 4-bit model ran on `dflash serve` with prefix caching disabled, so every measurement is a clean full prefill.
Result #1: Prefill vs context
Prefill throughput by model and context length. The MoE (green) towers over speculative decoding (blue) and the dense model (grey) — and barely sags as context grows. Higher is better.
*prefill throughput · time-to-first-token
At a realistic 24k-token agentic context, the MoE reaches the first token in 31 seconds, versus 141 seconds for dense + speculative decoding and 195 seconds for the plain dense model. That’s the MoE being ~4.5× faster than spec-decode and ~6.3× faster than dense — on the exact metric agentic coding lives and dies by.
The same data as the wait you actually feel (log scale, lower is better). At 24K tokens the gap is the difference between a 31-second pause and a 2–3 minute one — every turn.
Notice the MoE’s prefill barely sags as context grows (867 → 770 t/s). Sparse activation keeps per-token compute cheap, no matter how long the prompt gets.
Result #2: Decode — the plot twist
Flip to decode (token-generation speed) and the ranking inverts completely:
Decode throughput, higher is better. Speculative decoding (blue) wins this chart decisively — but decode isn’t the agentic bottleneck, so winning it doesn’t win the turn.
Speculative decoding is spectacular at decode — 145–182 tokens/sec, the fastest of the three by a wide margin. If you were running a chatbot, dflash would win going away.
But in agentic coding the replies are short, so this advantage barely moves the per-turn clock. Spec-decode optimizes the half of the problem that isn’t the bottleneck. That’s the whole story in one sentence.
Result #3: The `/clear` punchline
Here’s the subtlety that explains why so many people misdiagnose this. On the tiny `/clear`’d sub-prompts (49–65 tokens), the per-turn ranking inverts again:
At tiny context, there’s almost no prefill to pay, so turns are decode-dominated — and dflash’s fast decode makes it feel snappiest.
This is the trap. If you test your local setup with short prompts, speculative decoding looks like the winner. The MoE’s decisive advantage only appears once context grows and prefill takes over — which is exactly what happens the moment you point a real agent at a real codebase. Small prompts hide the gap; agentic prompts expose it.
Note: It’s also a great argument for prompt hygiene: `/clear` often. A `/clear`’d MoE turn finishes in ~3s; the same model on a cold 24k context takes ~31s to first token.
Why the MoE wins: the mechanism
It comes down to one number: active parameters per token.
- The dense 27B activates all 27B parameters for every token of prefill.
- The MoE 35B-A3B routes each token to a handful of experts and activates only ~3B parameters.
Prefill is a giant matrix-multiply over the prompt. Doing it with ~3B active parameters instead of 27B is roughly an order of magnitude less compute — which is exactly why the MoE prefills 6× faster despite being a larger model on disk. Speculative decoding can’t compete here because it doesn’t reduce prefill compute at all; it only saves verifier passes during generation.
Two nuances worth knowing
1. 4-bit prefills faster than 3-bit — at equal size. The dflash 4-bit model prefilled at 218 t/s vs the dense 3-bit model’s 131 t/s at 2k (~1.7× faster). That’s not the spec-decode draft — it’s the quantization scheme. My TurboQuant 3-bit path applies an online Hadamard rotation per layer, which costs real compute during prefill. Standard 4-bit affine skips it. (The 3-bit win is memory footprint and quality-per-bit, not prefill speed.) Above 16k, dflash’s prefill bends down (222 → 171 t/s) as O(n²) attention starts to bite.
2. KV-cache quantization is a memory win, not a speed win. I served the TurboQuant models with 8-bit-key / 3-bit-value KV-cache quantization, which keeps the cache tiny (well under 2 GB even at long context) so you don’t OOM on a 64 GB Mac. It doesn’t make prefill or decode faster — it makes long context possible.
From benchmark to a 4-minute stall:
While recording the Part 1 demo, I asked the local 4-bit 27B (the dflash setup) to build and run a full-stack FastAPI + React calculator app. It did. Then I asked it to stop the two dev servers — and it went silent for four minutes.

Part 1 Demo : four minutes lag.
It hadn’t crashed. The conversation had grown to 35,129 tokens — every file written, every tool result, plus the running servers’ console output. That turn missed the prefix cache, so the dense 27B re-prefilled all 35k tokens at ~143 tok/s ≈ 245 seconds before it could respond. (Memory was never the issue — it peaked at ~21 GB.)
This is the benchmark playing out in real life. Here’s what that exact 35,129-token cold prefill costs on each setup:
The MoE doesn’t make a cache miss disappear. It makes it survivable — a ~45-second annoyance instead of a four-minute stall. When you’re driving an agent that occasionally blows past its prefix cache (and it will — long-lived dev-server output is the fastest way to balloon a context), that 5× margin is the difference between “usable” and “I gave up and hit `/clear`.”
Two takeaways the stall makes concrete: `/clear` before an unrelated request (asking a 35k-token conversation to “stop the servers” re-reads all 35k first), and a sparse MoE buys you headroom for the times you forget.
How to reproduce this
Install the server and point it at a quantized MoE:
pip install -U turboquant-mlx-full

# Serve a sparse MoE with quantized weights AND a quantized KV cache
turboquant-serve \
 -model manjunathshiva/Qwen3.6-35B-A3B-tq3-g32 \
 -kv-k-bits 8 -kv-v-bits 3 -kv-min-tokens 128 \
 -prompt-concurrency 1 \
 -port 8787 \
 -chat-template-args '{"enable_thinking": false}'
Then bridge it to your agent (e.g. via claude-code-router for Claude Code) — Part 1 walks through that wiring step by step — and keep your context short: `/clear` between unrelated tasks is the single biggest speedup available to you, for free.
Caveats
- This measures speed, not quality. A 3-bit MoE and a 4-bit dense model are different on coding accuracy; that’s a separate study. Here I held the workload fixed and varied only the serving strategy.
- Single-user, single-stream. No batching. KV-quant forces sequential serving, which is correct for a personal coding assistant but not for a shared endpoint.
- 64 GB Apple Silicon, MLX backend. Your absolute numbers will differ; the ratios should hold, because they’re driven by active-parameter count, not the specific chip.
The takeaway
For local agentic coding on Apple Silicon, the speed lever isn’t the one everyone grabs:
1. Pick a sparse MoE. Active-parameter count, not total size, decides prefill speed — and prefill is the bottleneck.
2. Don’t count on speculative decoding. It makes decode fly, but decode isn’t where the wait lives.
3. Quantize the KV cache to make long context fit, and `/clear` aggressively to keep prefill cheap.
A sparse MoE you can run on a Mac will feel faster than a dense model twice its apparent sophistication — not because it’s smarter, but because it reads your enormous agent prompt with a tenth of the compute.
Resources
TurboQuant paper https://arxiv.org/abs/2504.19874 — Zandieh, Han, Daliri, Karbasi (2025).
TurboQuant-MLX on PyPI https://pypi.org/project/turboquant-mlx-full — `pip install “turboquant-mlx-full>=0.4.1”`
Qwen3.6–35B-A3B-tq3-g32 on HuggingFace https://huggingface.co/manjunathshiva/Qwen3.6-35B-A3B-tq3-g32 — the 35B streaming model card.
TurboQuant-MLX on GitHub https://github.com/manjunathshiva/turboquant-mlx — Source, issues, Apache-2.0.
DFlash project page (Z Lab)
https://z-lab.ai/projects/dflash/
DFlash reference implementation on GitHub:
https://github.com/z-lab/dflash
mlx-community/Qwen3.6–27B-4bit on Hugging Face
https://huggingface.co/mlx-community/Qwen3.6-27B-4bit
Draft — z-lab/Qwen3.6–27B-DFlash on Hugging Face
https://huggingface.co/z-lab/Qwen3.6-27B-DFlash