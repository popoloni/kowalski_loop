OpenCode is the “Linux of Agents”: and that’s the entire point
The Context sovereign: why AGENTS.md is the new LLM secret
JUN 28
 

I’ve been around the AI coding tools space long enough to see the pattern. Every few months, a new “revolutionary” tool drops with a flashy demo and a subscription wall.

Claude Code here, Cursor there, Copilot everywhere. And somehow, we’re all supposed to feel grateful that these companies are “democratizing AI.”

Truth to be told: we are the lab rats of this big experiment called Generative AI, where Big Techs release fancy tools they don’t even know the purpose. And then thy just tell us…

Show us what you can do!

They need us to prove them worth.

Basically burden has been outsourced… to You! We have all been drafted as a product tester.

No one asked you if you wanted this job. But suddenly, it’s your responsibility to figure out how to make AI useful in your life. You’re expected to:

Rewrite your prompts five times until the AI “gets it.”
Manually fact-check everything it says (because, surprise, it hallucinates like a sleep-deprived poet).
Stitch together three different AI tools just to complete one simple task.
More than innovation... It’s simply exhausting


What nobody told us is that we’re not actually in control. Every single one of these tools decides which model you can use, where your code lives, and what the AI remembers about your project. You’re renting a cage with nice curtains.

That’s why I nearly jumped out of my chair when I found OpenCode. Not because it’s perfect (it’s not) but because it represents something I’ve been craving since the first AI coding assistant launched: ownership.

Let me explain what I mean by “agent harness,” why OpenCode deserves the “Linux of Agents” moniker, and why this matters if you care about privacy, flexibility, or just not getting locked into another ecosystem.

TL;DR

Agent harnesses connect AI models to real work (file access, terminal, memory)
OpenCode is an open-source harness with 75+ provider support, local-first privacy, and the AGENTS.md system
It’s free, runs in your terminal, and keeps your code on your machine
it has 3 free models out-of-the-box
The trade-off: more setup than closed tools, but total ownership
If you care about privacy, flexibility, or just not another subscription… this is the path forward

The Moment That Changed Everything for Me

I’ll be honest: I didn’t immediately “get” OpenCode. The first time someone mentioned it, I thought, another AI coding tool? Pass.

I was deep in my Claude Code phase studies. Had the subscription, the VS Code extension, the whole ritual. It worked well. But there was this itch I couldn’t scratch:

Every time I started a new project, I’d have to re-explain my entire stack. The LLM knew nothing about my conventions, my file structure, my weird preference for certain patterns. And worse: if I stopped paying, all that “learning” disappeared. Poof.

Then I stumbled onto a blog post mentioning OpenCode’s AGENTS.md feature. The premise was simple: you drop a file in your project root, and the AI reads it like a manual. No more repeating yourself. No more context window wasted on setup explanations.

Wait, I thought. That should be obvious. Why isn’t everyone doing this?

That’s when I realized (better late than never): most tools don’t want you to own your context. They want you dependent on their cloud.

OpenCode was different.

Note: from now on, consider that everytime you read something related to Claude Code or Codex, you can apply the same principles and structure to Opencode too. The main difference: CALUDE.md becomes AGENTS.md

So What Actually Is an “Agent Harness”?

Before we go further, let’s make sure we’re on the same page. You keep hearing “harness” thrown around, but what does it actually mean?

Think of it this way: the model (Claude, GPT-4, Llama, whatever) is the brain. It can think, reason, write code. But it can’t do anything on its own. It can’t read your files. It can’t run terminal commands. It can’t remember what happened five minutes ago.

The harness is the body. It’s the scaffolding that gives the model:

File access ➡️ reading and writing where you need it
Terminal execution ➡️ running commands, tests, builds
Context management ➡️ what to include in the prompt, what to ignore
Memory ➡️ retaining state between sessions
Safety ➡️ permissions that stop it from doing something dumb (or malicious)
The formula everyone’s using in 2026 is simple:

Agent = Model + Harness

This is a real shift. It means you’re not locked into one provider’s “complete solution.” You can swap the brain while keeping the body. You can run a local model for privacy, then switch to an API for power, without learning a new tool.

OpenCode is one of those harnesses… but with a twist we’ll get to in a moment.

Why OpenCode Earned the “Linux” Label

Here’s the thing about Linux: it’s not the flashiest operating system. It’s not the most polished. But it runs everywhere, it lets you see under the hood, and nobody can tell you what you can and can’t do with it.

OpenCode is that philosophy applied to AI coding agents.

😂 By the way, opencode works perfectly on every Operating System, here Linux is only a title

Let me break down why:

1. Provider Agnostic (75+ Models and Counting)

OpenCode doesn’t care which LLM you use. Claude? GPT? Gemini? Local Llama running on your own machine via Ollama? All of the above.

Unlike Claude Code (Anthropic-only) or Copilot (OpenAI/Microsoft-only), OpenCode treats models like interchangeable parts. You configure your provider in a JSON file, or with Bifrost-CLI and you’re off.

For someone like me, who’s constantly benchmarking small models, testing quantization strategies, and pushing the limits of what runs on consumer hardware this is everything.

{
  “provider”: {
    “ollama”: {
      “npm”: “@ai-sdk/openai-compatible”,
      “options”: {
        “baseURL”: “http://localhost:11434/v1”
      },
      “models”: {
        “qwen2.5-coder:3b”: {
          “name”: “Qwen 3.5 2B Local”
        }
      }
    }
  }
}
That’s all it takes to use a local model. No cloud dependencies. No API bills. Just your hardware and your code. Your AI, your rules.

2. Privacy by Design (Your Code Stays Yours)

This is where OpenCode really stands apart. Most AI coding tools upload your code to the cloud, that’s how they work. Your context is processed on someone else’s servers.

OpenCode? Zero telemetry by default. Your code never leaves your machine unless you explicitly configure it to. You can run entirely offline with local models.

For developers working on proprietary code, sensitive projects, or just anyone who values privacy, this is huge. I’ve used it on client work where NDA clauses explicitly forbid cloud-based AI tools. OpenCode + Ollama was my lifeline.


3. The AGENTS.md Revolution

Remember how I said this feature caught my attention? Let me go deeper.

AGENTS.md is a file you drop in your project root. It contains everything the AI needs to know about your project:

What language/framework you use
Your coding conventions
File structure overview
Specific agent behaviors or constraints
# AGENTS.md
## Project Context
- This is a Python FastAPI project
- We use SQLAlchemy for database operations
- Tests are in `tests/` using pytest
## Conventions
- All async functions use `async def`
- Error responses follow `ErrorResponse` schema
- Use type hints everywhere
## Agent Behavior
- Always run tests before committing
- Never modify more than 5 files in one session
- Ask before running destructive commands
The first time I used this, I nearly cried. Five years of explaining my stack to AI assistants, and here comes a simple text file that solves it.

And here is the beautiful part: AGENTS.md is portable. It’s just a markdown file. You can version control it, share it with your team, customize it per project. The intelligence belongs to you, not the tool.

4. Skill System (Modular Powers on Demand)

OpenCode has a “skill” system that lets you load specific capabilities when needed. Think of it like plugins, but simpler.

Need to do a git release? There’s a skill for that. Database migration? There’s a skill for that too. You define skills in SKILL.md files, and OpenCode loads them dynamically.

This keeps the core tool lightweight while letting you extend it however you want. Just the powers you need.

5. Terminal-First (Where Developers Actually Work)

OpenCode lives in the terminal. Not a web interface. Not a browser-based IDE. The command line.

This matters more than you might think. The terminal is where I spend 90% of my coding time. It’s where build scripts run, git operations happen, and real work gets done. Having an AI agent that meets me there, rather than forcing me into a GUI, feels quite natural.

👉 Tip: for Windows OS users, I strongly recommend you to use the Git Bash terminal. AGENTS like to run commands linux style and Powershell fails 80% of the time!

There’s a TUI (Terminal User Interface) for interactive sessions and a CLI for one-shot commands:

opencode run “refactor this function to use async/await”
Simple and fast.

The Numbers Don’t Lie

OpenCode isn’t some niche project nobody uses. Here’s what’s happening:

179K+ GitHub stars (though the original repo was archived in September 2025, more on that below)
870 contributors building and maintaining the project
6.5 million monthly users as of 2026
Desktop beta available for macOS, Windows, and Linux
For context: Claude Code, Cursor, and Copilot are all well-known. But OpenCode’s community-driven growth is unprecedented in the AI coding space.

The Comparison (Because You’ll Ask)

Here’s how OpenCode stacks up against the big players:


The trade-offs? OpenCode can be token-inefficient on some API calls (you’re not using the provider’s optimized integration). And there’s more configuration overhead than a “magic box” like Cursor.

Considering the latest complains about how Anthropic has cut the reasoning ration of their flagship model, and that it does not use KV-cache efficiently, Claude Code is becoming a niche product (even if powerful).

But if you care about ownership, flexibility, and running things locally, the choice is clear.

And if you use Bifrost-CLI as harness configurator together with its own gateway, the hurdles are almost totally removed.

Similar Tools Worth Knowing

OpenCode isn’t the only player in the “sovereign agent” space. Here’s who else is fighting the good fight:

Aider: Git-native CLI agent, great at version control integration
Cline: Terminal-based, supports 10+ providers, focused on cost management
Continue.dev: IDE extension for open LLMs, autocomplete-focused
OpenHands: Formerly OpenDevin, can fix GitHub issues autonomously
Agno: Lightweight, minimalist, avoids LangChain bloat
Each has strengths, but OpenCode’s combination of provider flexibility, AGENTS.md, and privacy-first design makes it my daily driver.


Getting Started (Your Turn)

Enough theory. Let’s build your own sovereign knowledge base. We’ll use OpenCode as the harness and the available free tier models (3 of them) coming with the installation.


the 3 free models coming with opencode
Note: if you want to know how to use llama.cpp as the local engine to ensure your data stays entirely on your machine, you can read the articles in the Series LLM-wiki (link at the end of the article).

1. The Foundation (Windows Setup)

On Windows, the easiest way to manage your AI tools is through Chocolatey. Open PowerShell with Administrator rights and run:

# PowerShell
# Install OpenCode and Git
choco install opencode git -y
# Refresh your environment variables
refreshenv
You can read more about Chocolatey here

👉 Tip: While you can use PowerShell, most AI agents prefer running Unix-like commands. I highly recommend using Git Bash (installed above) as your primary terminal to avoid command parsing errors.

2. Prepare Your “Digital Office”

Create a root folder (e.g., C:\My-project) and open the king of the agents: opencode.

Open GIT Bash in your project directory (remember that we called it C:\My-project ).


open with Git Bash here — image as a reference
Go in Plan mode (TAB key) and start asking what you want to build, how it is better to setup folders and files.

When the LLM has a clear plan and it has all detailed for you, mode to Build mode (TAB key) and say yes to proceed with implementation.

👉 Remember: in Plan mode opencode cannot touch any of your files!

Opencode will create an AGENTS.md file in your root folder. This is your “Boss” file or Standard Operating Procedure. This file tells the agent exactly how to handle your project.


The Bigger Picture

What I’m really excited about is what OpenCode represents: the shift from “Model as Product” to “Harness as Infrastructure.”

We’ve spent years arguing about which model is “best.” Claude vs. GPT. Sonnet vs. Opus. Qwen vs. Llama. But the real battle is moving underground, to the layer that actually connects these models to your work.

OpenCode understands this. It’s not trying to be the smartest model. It’s trying to be the best glue: the layer that makes any model work for you, on your terms.

That’s the Linux philosophy. It is so transparent that you can use for whatever you want: you are in control!

Why This Matters (Especially for Us “Poor-GPUguys”)

I’ve been open about my situation: at 49, I’m running AI experiments on a 2016 laptop with integrated graphics. No GPU. No cloud budget. Just determination and way too much curiosity.

For years, the AI coding tool industry pretended people like me didn’t exist. Every demo showed cloud-based solutions processing code on distant servers. Many “free” tier required credit card verification or limited requests per day. Every “local” solution demanded hardware I couldn’t afford (probably the only model worth of mentions for the speed on CPU is qwen3.5–0.8b, but it is not so accurate with agents).

OpenCode changes that calculus completely.

When I first got OpenCode running with llama.cpp server on my modest setup, I used Qwen3.5–2b at 2 billion parameters. That’s a tiny model by industry standards, nowhere near the 70B+ monsters companies like Anthropic and OpenAI use. But you know what? It worked.

Not perfectly and not always (2b is still a smal format). But enough to:
- Explain codebases I was unfamiliar with
- Refactor functions I didn’t want to touch manually
- Generate test cases that saved me hours
- Help me understand unfamiliar APIs

The point is not that small models replace Claude or GPT. The point is that you don’t need the most expensive option to be productive. You need the right tool for your constraints.

And OpenCode gives you that choice. Run a tiny quantized model on your CPU. Run a larger one when you have access to better hardware. Switch between them based on what you’re working on. You decide, not the subscription tier.

👉 Tip: I usually use big models (the free ones I always talk about) to create the structure, the AGENTS.md and the commands and skills. After that I switch to local models with llama.cpp


The Industry Is Watching (Whether They Admit It or Not)

Here’s something interesting: even as OpenCode was gaining traction, the big players started paying attention.

Cursor added more provider options. GitHub expanded Copilot’s model choices. Anthropic started talking more about “hybrid” deployments. It’s almost like they realized the market was shifting.

The “harness as infrastructure” paradigm is becoming the new standard. Because here’s the truth nobody in the industry wants to admit openly: model quality alone isn’t a sustainable moat.

Anyone can access Claude through API (paying). Anyone can use ChatGPT (paying). The differentiation is in the experience: how the model connects to your workflow, how much it knows about your project, how much control you have.

And that’s exactly what OpenCode nailed. While everyone else was fighting over who had the smartest model, OpenCode built the best bridge between models and developers.


Real-World Example: LLM-wiki implementation

Let me give you a concrete example of how OpenCode saved me time.

I used this exact setup to organize my own research. I had years of scattered notes on AI quantization and “catastrophic forgetting” that were essentially useless because I could never find the right connection when I needed it.

It is my personal implementation of the LLM-wiki project by A.Karpathy, as I reported it in my previous series.


Instead of just “chatting” with a model, I pointed OpenCode at my AGENTS.md and my /raw folder full of technical papers. I used a custom command I wrote, //wiki-list, to see everything I hadn’t processed yet.

The Workflow:

I dropped three new PDFs about “KV-cache quantization” into /raw.
I told OpenCode: “Process the new files.”
The agent — acting as a Librarian — didn’t just summarize them. It opened my existing Llama_CPP_Optimization.md in the /wiki folder and appended the new findings, creating a compounding record of knowledge.
The Result: Because I ran this locally using llama.cpp, it cost me zero cents in API tokens, even though the context window was massive. More importantly, the next time I started a project, I didn’t have to “re-teach” the AI. I just said, “Read the wiki page” and it was instantly up to speed.

It moved me from “renting” intelligence for a single session to owning a growing digital brain.


The Configuration That Actually Works

One thing I glossed over earlier but deserves more attention: OpenCode’s configuration system. It’s JSON-based, declarative, and surprisingly powerful once you understand it.

👉 Remember I explained how to connect my llama.cpp server running on my crappy MiniPC used only to serve Qwen3.5–2B

Here’s my actual working config for local development:

{
  “$schema”: “https://opencode.ai/config.json”,
  “provider”: {
    “ollama”: {
      “npm”: “@ai-sdk/openai-compatible”,
      “options”: {
        “baseURL”: “http://localhost:11434/v1”
      },
      “models”: {
        “qwen3.5”: {
          “name”: “Qwen 3.5 2B Local”
        },
        “gemma4”: {
          “name”: “Gemma 4 E2B Local”
        }
      }
    }
  },
  “agent”: {
    “default”: “build”,
    “timeout”: 300000
  }
}
A few tips from my experience:

Start with small models. Qwen3.5–2b at its small form factor is surprisingly capable for its size. Gemma-4-E2B is another solid choice.
Use project-level configs. Instead of a global config, put .opencode/opencode.json in each project. This lets you customize per-project. You can even put it in the root directory of the project!
Name your models clearly. “Qwen 3.5 2B Local” is easier to remember than “qwen3.5–2b” when selecting in the UI.
Common Pitfalls (So You Don’t Fall Into Them)

I’ll be honest: OpenCode isn’t all smooth sailing. Here are the issues I’ve run into so you can avoid them:

1. First-Run Configuration Overwhelm

The first time you set up OpenCode, there’s a learning curve. Provider configs, model selection, AGENTS.md structure, it adds up.

Solution: Start simple. Use the defaults. Add complexity only when you need it.

2. Model Selection Is Everything

Not all models work equally well for all tasks. Some are better at reasoning, others at code generation.

Solution: Test different models on your actual workload. Don’t assume bigger is always better.

To work with agents the LLM you are looking for must have at least 2 features:

agent ready ➡️ can accept in the prompt and outputs agents calls
tools ready ➡️ the prompt template must be able to return tools call
When using llama.cpp server, you need to enable the jinja template flag (--jinja), like this example:

.\llama-server.exe -m .\Qwen3.5-2B-Q4_K_M.gguf --jinja -c 64000 -ngl 0 -ctk q4_0 -ctv q4_0 --mmap --port 11434 
3. Context Window Limits

Even with AGENTS.md, you’re still constrained by context windows. If your project is massive, you can’t shove everything in.

Solution: Be strategic about what goes in AGENTS.md. Focus on high-level context, not file-by-file details.

If you are using llama.cpp remember to add the flags to quantize the KV-cache, to save memory and extend your context window capabilities

.\llama-server.exe -m .\Qwen3.5-2B-Q4_K_M.gguf -c 64000 -ctk q4_0 -ctv q4_0
Here above we quantized the KV cache in q4_0 format

4. Local Model Speed

Let’s be real: local models on CPU are slower than cloud APIs. Like, significantly slower.

Solution: This is the trade-off. Lower cost, more privacy, less speed. Pick based on your priorities.

If you are using llama.cpp for local models, remember to use the threads flag and the memory map option

.\llama-server.exe -m .\Qwen3.5-2B-Q4_K_M.gguf -c 64000 -ngl 0 -t 4 --mmap 
Here above we set the number of threads to 4 (remember to leave at least 1 or 2 cores available for your OS)

5. Documentation Gaps

OpenCode’s documentation has improved but can still be sparse on edge cases.

Solution: Join the community (Discord, GitHub discussions). The maintainers and users are helpful.


The Road Ahead

OpenCode is not perfect. The original repo getting archived in 2025 was concerning (though development continues via forks). The desktop app is still in beta. Token efficiency on some API calls could be better.

But here’s what keeps me optimistic: the core philosophy is right.

We need open-source tools that respect user ownership. We need harnesses that work with any model. We need AI coding assistants that don’t require a credit card to start.

OpenCode delivers all of that. And the community: 850 contributors, 6.5 million users, is proof that people want this.

I’m not saying it’ll replace Claude Code or Cursor. Those tools have legitimate strengths (model quality, polish, IDE integration). But for people like me (the “Poor-GPUguys” obsessed with privacy, the half writers half philosophers, who want control) OpenCode is exactly what we’ve been waiting for.

Conclusions

I’ve been using OpenCode for a few months now, and it’s fundamentally changed how I work with AI coding tools. The combination of local models + AGENTS.md + zero telemetry is exactly what I didn’t know I needed.

Try it on a small project.

Create your first AGENTS.md.

Run a local model.

Feel what it’s like to be in control again.

Let me know how it goes. I’m genuinely curious: has the “Linux of Agents” clicked for you too?

OpenCode is not another AI chatbot. It is an “agent” that can act on your code, documents and projects.

Whether you prefer the classic terminal, a modern desktop app, or your favorite IDE, OpenCode gives you the power to use any AI “brain” you want.

Most importantly, you can run it entirely locally to keep your sensitive work and NDAs completely private.

Table of Contents

The New Frontier: From Command Lines to AI Agents
What Exactly is OpenCode? (The Mechanism)
One Tool, Three Faces: CLI, Desktop, and IDE
The Power of Choice: Why Provider Freedom is Everything
Privacy: Your Personal AI Sanctuary
OpenCode vs. Claude Code: A Respectful Comparison
Conclusion: The Revolution has Begun
By the way, this is a Series of 6 articles:

Part 1 — The OpenCode revolution: more than just another chatbot
Part 2 — Beginner to expert: your first 60 seconds with OpenCode
Part 3 — Teaching your Agent: mastering context with AGENTS.md
Part 4 — The toolkit: Commands and Skills in OpenCode
Part 5 — Your private AI Agency: the local powerhouse
Part 6 — Advanced Orchestration: multi-agent systems and plugins


when you start opencode
The New Frontier: From Command Lines to AI Agents

If you are anything like me, you probably remember the first time you saw a cursor blinking on a black screen. There was something almost magical about it. You typed a command, and the computer obeyed.

It was a direct, unmediated conversation between a human and a machine.

We lived through the era of MS-DOS, the rise of the graphical user interface, and the birth of the modern web. We have seen technology change the world several times over.

But lately, it feels like we have entered a new kind of frontier. We are no longer just giving commands to a machine; we are starting to collaborate with it. We are entering the era of the “AI Agent.”

For a while, the hype has been all about chatbots. You ask a question, and the chatbot gives you an answer. It is impressive, certainly. But if you are a developer or someone who works with technical data, a chatbot is often not enough.

A chatbot can tell you how to fix a bug, but it cannot actually reach into your files and fix it for you. It can explain a concept, but it cannot set up your environment.

That is where OpenCode enters the picture. It represents a shift from “AI that talks” to “AI that does.”


opencode comes with a web app out of the box
What Exactly is OpenCode? (The Mechanism)

I like to use an analogy to explain the difference between a traditional AI chatbot and an agent like OpenCode.

Imagine you are planning a road trip. A traditional chatbot is like a GPS navigation system. You type in your destination, and it gives you a brilliant, highly accurate step-by-step route. It tells you exactly where to turn, but it stays mounted to your dashboard. It cannot step on the gas, it cannot turn the wheel, and it certainly won’t drive you to your destination while you rest.

An agent, on the other hand, is like a self-driving autopilot. You don’t just ask it for directions; you give it a destination and permission to drive. You say, “Take me to the hotel,” and the vehicle actually moves. It accelerates, navigates traffic, reads road signs, and steers the car until you arrive safely.

OpenCode is that autopilot for your development workflow.

When you run OpenCode, it does more than just process your text. It “sees” your project. It uses something called Language Server Protocols (LSP) to understand the structure of your code. It knows which function calls which variable, which files are related, and how your entire application is stitched together.

When you give it a task, it doesn’t just output text in a chat window. It uses “tools.” It can read a file, it can edit a line of code, it can run a test command in your terminal, and it can even check the output of that test to see if it passed. It is a loop of reasoning and action. It thinks, it acts, it observes the result, and then it thinks again.




opencode CLI, Desktop and Web
One Tool, Three Faces: CLI, Desktop, and Web

One of the first things people ask me is, “Do I have to be a terminal wizard to use this?”

The answer is a resounding no.

In the old days, if you wanted to do serious work, you had to master the command line. There was no way around it. While I still love the terminal (there is a certain satisfaction in a well-crafted command, isn’t there?), I know that not everyone wants to live in a black box with white text.

OpenCode has been built with three different “faces” to suit different workflows:


1. The Classic CLI (Command Line Interface)

This is for the purists. It is fast, lightweight, and lives right where your code lives. If you are already a terminal user, this will feel like home. It is incredibly efficient for quick tasks, automation, and those who want zero distractions.


2. The Modern Desktop App

This is perhaps the most exciting development for many. OpenCode now offers a desktop application, currently in beta. This provides a much more visual, intuitive experience. If you prefer a structured interface with buttons, menus, and a clear view of your workspace, the desktop app is for you. It brings the power of an agent into a package that feels familiar to anyone who has used a modern operating system.


3. The web app

OpenCode can run as a web application in your browser, providing the same powerful AI coding experience without needing a terminal.

Start the web interface by running:

opencode web
This starts a local server on 127.0.0.1 with a random available port and automatically opens OpenCode in your default browser.


No matter which “face” you choose, the “brain” remains the same. You get the same intelligence and the same capabilities, just delivered in a way that fits your personal style.


free models out of the box
The Power of Choice: provider Freedom is Everything

We have all been there. You sign up for a service, you get comfortable, and then suddenly, the rules change. The price goes up, the features are moved behind a new paywall, or the service becomes unreliable. In the world of AI, this is a very real and very common problem.

First thing first: opencode comes with at least 3 free models, good one, with a generous free tier out of the box.

Most of the big names in AI are “walled gardens.” If you want to use the best models from Anthropic, you have to use their platform. If you want to use OpenAI, you are tied to them. This “vendor lock-in” is a major headache for professionals and businesses alike.

OpenCode takes a completely different approach. It embraces what I call “Provider Freedom.”

OpenCode does not care which “brain” you use. It is designed to connect to over 75 different AI providers. You can use the massive, cutting-edge models from Google or OpenAI when you have a truly difficult problem. You can use the specialized models from NVIDIA’s NIM platform.

I wrote about how to do it in these articles:

Are you too a Poor-GPU-guy? Here’s how to run 400B parameter Models for free
Are you too a Poor-GPU-guy? Here’s how to run 400B parameter Models for free
MAY 10
Read full story
Opencode with local AI:

OpenCode is the “Linux of Agents”: and that’s the entire point
The Context sovereign: why AGENTS.md is the new LLM secretmedium.com

LLM-wiki local & locall LLM: part 2
How to implement LLM-Wiki with opencode and llama.cpp, all tricks includedmedium.com

And here is the best part: you don’t always have to pay a fortune. Many of these providers offer incredibly generous free tiers. You can use Google’s Gemini or even some of the free resources provided through OpenCode itself to get started without spending a single cent.

This flexibility means you are never stuck. If a new, better model is released tomorrow, you don’t have to wait for a new software release or a change in your subscription. You simply plug the new model into OpenCode and keep moving. You are in control of your tools, not the other way around.


Privacy: Your Personal AI Sanctuary

Now, let’s talk about something that is close to my heart: privacy.

If you have worked in any professional capacity for the last few decades, you know that data is gold. And because it is gold, people want to protect it. We have NDAs (Non-Disclosure Agreements) to respect. We have proprietary algorithms, sensitive client information, and personal data that must never, ever leave our control.

The biggest fear with cloud-based AI is the “black box” problem. When you send your code to a cloud provider, where does it go? Is it being used to train their next model? Is it sitting on a server somewhere, vulnerable to a breach? For many professionals, the answer to these questions is a “no thanks.”

OpenCode was built with a “privacy-first” mindset.

Because OpenCode supports local models through tools like Ollama or llama.cpp, you can choose to run the entire intelligence of your assistant on your own hardware. This means the “thinking” happens right there on your machine. Your code, your prompts, and your project structure never leave your hard drive.

You get all the benefits of an AI agent, the reasoning, the coding, the assistance, but with the peace of mind that comes from knowing your data is under your physical control. It is like having a brilliant assistant who works in a soundproof room inside your own house. They are incredibly helpful, but they never, ever talk to the outside world.

For anyone working with sensitive enterprise code or personal projects, this is not just a “feature.” It is a necessity.


OpenCode vs. Claude Code: A Respectful Comparison

I have spent some time with Claude Code, and I want to be clear: it is an excellent tool. It is fast, it is polished, and it is undeniably powerful. If you are already deep within the Anthropic ecosystem, it is a fantastic experience.

However, there is a fundamental difference in philosophy.

Claude Code is a specialized tool designed to work within the Anthropic ecosystem. It is like a high-end, luxury sports car. It is beautiful, it is incredibly fast, and it performs brilliantly. But it only runs on one very specific, very expensive type of fuel. If you want to change how you power it, you simply cannot.

And it is very expensive.

OpenCode is more like a high-performance engine that you can mount on whatever vehicle you like. You can put it in a rugged off-road vehicle (the CLI), a comfortable sedan (the Desktop app), or a sleek racing car (the WEB app). And most importantly, you can choose your fuel. You can use premium gasoline (the top-tier cloud models), or you can run it on electricity that you generate yourself (local models via Ollama or llama.app).

OpenCode doesn’t try to replace the power of models like Claude; it simply gives you the freedom to use that power whenever and however you choose, without being trapped by a single provider’s walls.


Conclusion: The Revolution has Begun

We are standing at the edge of a massive shift in how we interact with technology. The era of the “passive” computer is ending, and the era of the “active” partner is beginning.

OpenCode is one of the first tools to truly embrace this shift, offering a bridge between the power of the cloud and the absolute necessity of local privacy. Whether you are a seasoned veteran of the command line or someone who prefers a more visual, modern interface, there is a way for you to harness this new power.

The revolution is a new approach: humans gaining new, incredibly powerful tools that allow us to reach further, build faster, and work more securely than ever before.

In my next article, I am going to get my hands dirty. I will walk you through the “Zero to Hero” process, showing you exactly how to install OpenCode and get it running in less than sixty seconds. We will explore how to connect your first provider and start your very first session.

The journey is just beginning. I hope you will join me.