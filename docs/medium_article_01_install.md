The Ultimate Local AI Setup Guide for Apple Silicon using DFlash
Here is the definitive, end-to-end master guide for setting up a fully local, agentic Claude Code environment on Apple Silicon — this guide incorporates every bug fix, timeout patch, and memory optimization required to run flawlessly on both a 16GB and a 64GB machine using DFlash: Block Diffusion for Flash Speculative Decoding

Enrico Papalini
Enrico Papalini
11 min read
·
6 days ago





Press enter or click to view image in full size

If you are used to the instantaneous speed of Anthropic’s cloud servers, building and tuning a local inference engine might feel like a lot of heavy lifting. However, running an agentic coding loop locally on Apple Silicon fundamentally changes how you interact with AI for software engineering.
Here is a breakdown of why this approach matters, the realities of the trade-offs, and the hard data behind why we chose these specific architectures.
Why Run Agentic AI Locally?
The primary drivers for pulling an AI agent offline are privacy, cost, and availability.
When you use Claude Code or Cursor connected to the cloud, your entire proprietary codebase, API keys accidentally left in .env files, and internal architectural decisions are packaged into a massive prompt and transmitted to external servers. For enterprise IP, defense, or strict NDA work, this is often a non-starter.
Running a model on your Mac ensures absolute data sovereignty — your code never leaves your SSD. Additionally, because agentic loops fire dozens of automated sub-requests to read directories, lint files, and rewrite functions, the API token costs can spiral quickly. A local setup incurs zero recurring costs and works perfectly whether you are in an office or offline on a flight.
The Trade-offs: Pros and Cons
While local models are incredibly capable, they are not a 1:1 replacement for flagship cloud models. It is crucial to set realistic expectations.
Press enter or click to view image in full size

Performance Benchmarks: The “Prefill” Bottleneck
The hardest lesson in local agentic coding is that generation speed is not your bottleneck. Tools like Claude Code send enormous prompts (system instructions, file contents, tools) on every single turn — easily reaching 20,000 to 30,000 tokens.
This means the wait time you feel is almost entirely Prefill (Time-to-First-Token), not Decode (token generation).
Here is how the three main local setups benchmarked against a realistic 24,000-token agentic context on an Apple Silicon Mac:
Press enter or click to view image in full size

Three models benchmarked — Qwen3.6 Dense in standard configuration, with DFlash (Best for generating huge blocks of code after the initial wait) and Sparse (Up to 6x faster at reading the prompt because it only uses 3B active parameters per token)
Key insight: Speculative decoding (DFlash) makes the model type incredibly fast, but it does nothing to help the model read. If you have a 64GB Mac, you can use DFlash and rely on your massive RAM to cache the reading phase. If you have a 16GB Mac, you must use the MoE model, or you will be waiting minutes for every single response.
DFlash: Block Diffusion for Flash Speculative Decoding
To understand DFlash, you have to understand the fundamental law of running Large Language Models: Token generation is severely memory-bound.
When an LLM generates text (the decode phase), it must fetch every single weight of the model from your Mac’s RAM into the processing cores just to predict a single token. If you are running a 27B model, your Mac has to move roughly 15 to 20 GB of data through memory bandwidth for every single letter it types. This is why native generation on large local models is capped at sluggish speeds (often 8 to 15 tokens/sec).
DFlash is a specialized framework designed to break this bottleneck on Apple Silicon using an advanced implementation of lossless speculative decoding.
Press enter or click to view image in full size

Architectural schema for DFlash: Block Diffusion for Flash Speculative Decoding — https://github.com/z-lab/dflash
The Core Mechanism: Draft & Verify
Instead of forcing the massive, slow model to do all the work, DFlash splits the generation into a high-speed partnership between two distinct models loaded into your Mac’s unified memory:
The Draft Model (z-lab/Qwen3.6-27B-DFlash): A tiny, highly optimized 2-billion parameter model. Because it is small, it flies through memory, predicting a "block" of potential upcoming tokens ($\gamma$ tokens) very quickly.
The Target Model (mlx-community/Qwen3.6-27B-4bit): The full 27-billion parameter brain. It steps in to evaluate the draft model's proposed block.
[2B Draft Model] ───Proposes a block of 6 tokens───> [27B Target Model]
                                                             │
<───Keeps accepted tokens, corrects first mistake────────────┘
The Mathematics of the Speedup
Normally, if a model generates 6 tokens, it must perform 6 sequential memory sweeps across its entire parameter bank.
DFlash changes the game: the target model takes the 2B draft’s proposed block and evaluates all 6 tokens simultaneously in a single, batched forward pass.
If the target model accepts the draft’s tokens, you get 6 tokens for the exact memory cost of 1 token.
If the draft model makes a mistake on token 4, the target model truncates the block, accepts the first 3, corrects token 4 on the spot, and throws away the rest.
Because the verification pass runs as a highly efficient matrix multiplication instead of sequential lookups, it achieves a massive throughput win. In practice, the DFlash 2B draft model matches the 27B target’s output distribution so accurately that it achieves an 80–94% acceptance rate (~5.9 tokens accepted per verification cycle), accelerating token generation up to 120 tokens/second.
The Hardware Secret: MLX and Async Weight Materialization
DFlash isn’t just a generic algorithm; it was co-designed to exploit the specific hardware architecture of Apple Silicon Unified Memory and the MLX framework.
During development, engineers found that writing custom, monolithic kernels to handle memory lookup actually slowed things down. DFlash succeeds by leaning on MLX’s native mx.async_eval (asynchronous evaluation) engine:
CRITICAL PATH TIMELINE:
Standard Execution:  [ Fetch 4-bit Weights ] ──> [ Compute MatMul ] ──> [ Next Token Loop ]
                                                                             (Stalled)
DFlash + MLX:        [ Target Verifier Pass (Async) ]
                     └───> Overlaps with [ 2B Draft Compute ] (Hides memory latency)
By streaming the verification pass asynchronously, the heavy memory-bound process of pulling the 4-bit target model weights off the Mac’s RAM occurs concurrently in the background while the 2B draft model is computing its next block proposal. The memory transfer latency is effectively hidden behind the compute time, allowing the M-series GPU to stay continuously saturated.
Lossless Preservation
The most critical feature of DFlash architecture is that it is mathematically lossless.
It does not approximate or degrade the quality of the model like a lower-bit quantization or a distillation trick would. Because the target 27B model strictly validates every single token according to its original probability distribution before committing it to the screen, the output text is 100% identical to running the heavy 27B model entirely on its own. It is simply a smarter scheduling pipeline that coaxes desktop-class generation speed out of local hardware.
From Theory to Practice: Building Your Local Engine
Understanding the mechanics of speculative decoding and unified memory bottlenecks is crucial for setting realistic expectations, but the real magic happens when you finally see it running on your own machine.
Transforming your Mac from a standard developer workstation into an isolated, high-speed agentic coding environment requires deliberate configuration. Out of the box, tools like Claude Code are hardwired to reach out to the cloud. To force them offline, we have to intercept their requests, bypass their cloud-first defaults, manage strict Python virtual environments, and fine-tune a local router to feed them data exactly the way they expect.
Now that the theoretical foundation is set, it is time to get our hands dirty and build the engine.
The hardware you are running dictates the path you must take. A machine with 16GB of unified memory cannot brute-force its way through massive context windows and requires the surgical precision of the Sparse MoE architecture. Conversely, a 64GB machine has the sheer capacity to absorb massive prompts, allowing us to leverage the DFlash framework for blistering generation speeds.
Whether you are maximizing efficiency on a 16GB Mac or unleashing the raw capacity of a 64GB Max, the following master guide will walk you through exactly how to install, configure, and optimize your local AI workspace from scratch. Let’s set up your machine.
Phase 1: Universal System Prerequisites
Do this once, regardless of your hardware.
1. Install Homebrew
Open your terminal and run:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
Run the two echo and eval commands it prints at the end to add it to your PATH.
2. Install Python 3 and Node.js
brew install python node@20
3. Pre-emptive Fix: Node.js icu4c Library Crash
Homebrew frequently breaks Node dependencies on fresh installs. Fix it immediately:
brew update
brew reinstall node@20
brew link --overwrite node@20
Verify it works without throwing a dyld error:
node --version
4. Create the Dedicated Python Environment
Never install AI packages globally. Create an isolated workspace:
mkdir -p ~/local-llm-workspace
cd ~/local-llm-workspace
python3 -m venv env
source env/bin/activate
(You must run cd ~/local-llm-workspace && source env/bin/activate every time you open a new terminal).
5. Install Claude Code CLI
Bypass the modern npm script-blocking security protocol that prevents Claude Code from installing:
npm config set allow-scripts=@anthropic-ai/claude-code --location=user
npm install -g @anthropic-ai/claude-code
6. Authenticate with Hugging Face
You need an active token to download gated models (like the DFlash draft).
Go to Hugging Face and accept the license agreement.
Go to your HF Settings -> Access Tokens and create a Read token.
In your terminal (with the env active), run:
pip install -U "huggingface_hub[cli]"
hf auth login
Paste your token when prompted (it will be invisible).
Phase 2: Choose Your Hardware Path
Path A: The 16GB Strategy (Mac Mini M4)
16GB unified memory cannot hold a dense 27B model for agentic coding. You must use a Sparse Mixture-of-Experts (MoE) model with KV-cache quantization to ensure fast prefill speeds and prevent memory crashes.
1. Install the TurboQuant Server and Bridge
pip install -U turboquant-mlx-full
npm i -g @musistudio/claude-code-router
2. Configure the Router Bridge
mkdir -p ~/.claude-code-router
nano ~/.claude-code-router/config.json
Paste this configuration (which includes the 10-minute timeout fix and pinned context fix):
JSON
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "Providers": [
    {
      "name": "turboquant",
      "api_base_url": "http://127.0.0.1:8787/v1/chat/completions",
      "api_key": "local",
      "timeout": 600000,
      "models": ["manjunathshiva/Qwen3.6-35B-A3B-tq3-g32"],
      "transformer": { 
        "use": [ ["maxtoken", { "max_tokens": 8192 }], "enhancetool" ],
        "context_window": 32000,
        "system_prompt_caching": true
      }
    }
  ],
  "Router": {
    "default": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "background": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "think": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "longContext": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32",
    "longContextThreshold": 30000,
    "webSearch": "turboquant,manjunathshiva/Qwen3.6-35B-A3B-tq3-g32"
  }
}
CTRL+O and ENTER and CTRL+X to save.
3. Start the Server
turboquant-serve \
 --model manjunathshiva/Qwen3.6-35B-A3B-tq3-g32 \
 --kv-k-bits 8 --kv-v-bits 3 --kv-min-tokens 128 \
 --prompt-concurrency 1 \
 --port 8787 \
 --chat-template-args '{"enable_thinking": false}'
Path B: The 64GB Strategy (M2 Max)
With 64GB, you prioritize raw coding accuracy by running a high-precision 4-bit dense model, using DFlash for speed, and allocating a massive chunk of RAM to eliminate cache-thrashing.
1. Install the Server and Bridge
pip install dflash-mlx
# Applies local compatibility fixes for Qwen 35B DFlash drafts and Gemma 4 unified MLX repos.
python bin/patch_dflash_mlx.py
npm i -g @musistudio/claude-code-router
2. Pre-emptive Fix: Bypass the 300-second Download Timeout
The DFlash server will kill itself if the draft model takes longer than 5 minutes to download. Pre-download it manually:
hf download z-lab/Qwen3.6-27B-DFlash
3. Configure the Router Bridge
mkdir -p ~/.claude-code-router
nano ~/.claude-code-router/config.json
Paste this configuration (with the 10-minute timeout fix and pinned context fix):
JSON
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "Providers": [
    {
      "name": "dflash",
      "api_base_url": "http://127.0.0.1:8787/v1/chat/completions",
      "api_key": "dflash-local",
      "timeout": 600000,
      "models": ["mlx-community/Qwen3.6-27B-4bit"],
      "transformer": { 
        "use": [ ["maxtoken", { "max_tokens": 8192 }], "enhancetool" ],
        "context_window": 32000,
        "system_prompt_caching": true
      }
    }
  ],
  "Router": {
    "default": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "background": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "think": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "longContext": "dflash,mlx-community/Qwen3.6-27B-4bit",
    "longContextThreshold": 30000,
    "webSearch": "dflash,mlx-community/Qwen3.6-27B-4bit"
  }
}
CTRL+O and ENTER and CTRL+X to save.
4. Start the Server (Aggressive Caching)
This command safely dedicates 24GB strictly to the prefix cache, stopping the model from “forgetting” the start of the conversation when background tasks run.
dflash serve \
  --model mlx-community/Qwen3.6-27B-4bit \
  --draft-model z-lab/Qwen3.6-27B-DFlash \
  --host 127.0.0.1 --port 8787 \
  --verify-mode adaptive \
  --max-tokens 2048 \
  --chat-template-args '{"enable_thinking": false}' \
  --prefix-cache-max-entries 64 \
  --prefix-cache-max-bytes 24GB \
  --no-clear-cache-boundaries

The Dflash server is up and running
Phase 3: Launching & Operational Workflow
Regardless of which path you chose, connect your CLI:
Open a new terminal tab (no need to activate the Python env).
Clean up any conflicting API keys that force Claude to the cloud:
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY
Restart the router daemon to apply the JSON configuration:
ccr restart
Launch the interface:
ccr code
Press enter or click to view image in full size

The usual Claude code interface running against local model
Crucial Step: When the UI opens, type /model and select your local bridged model to absolutely guarantee it does not try to ping the Anthropic Cloud.
The Golden Rule for Local Models
Local agentic coding is prefill-bound and generation-limited. To achieve instant results and avoid “churning” timeouts:
Never ask for massive files at once. Do not ask for “Implement a full clone of PacMan arcade”.
Force Atomic Steps. Plan the architecture first. Then ask it to write only the HTML structure. Then only the CSS. Then only the specific Javascript function.
Use /clear aggressively. If you switch from building the UI to debugging a database connection, type /clear. Flushing the 18,000-token context history restores prefill times to zero.
Press enter or click to view image in full size

the resulting code
Conclusion
Now that you have the infrastructure to run powerful agentic loops entirely offline, the real challenge begins: moving from unstructured “vibe coding” to reliable, reproducible engineering. Blazing-fast token generation is only half the equation; how you constrain and guide that local model determines whether it produces production-ready code or just faster hallucinations. I’d love to hear how you are managing this transition in your own daily workflows. Are you still relying on complex prompt engineering, or are you adopting more formal, architectural methodologies? Drop your experiences in the comments below, and if you’re looking for a structured way to orchestrate these local agents, feel free to explore the Enterprise SDD framework on my GitHub or dive into the broader methodology in the Non-Deterministic Software Engineering series.

Non-Deterministic Software Engineering series is available on Amazon.com