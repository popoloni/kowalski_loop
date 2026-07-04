#!/usr/bin/env python3
"""Autonomously build a Kowalski plan.json from a high-level goal.
Requires dflash running on :8787.  Usage: python -m llmstack.tools.build_plan "your project goal"
"""
import json, os, sys, urllib.request

CONFIG    = json.load(open("llmstack_config.json")) if os.path.exists("llmstack_config.json") else {}
DEV_ROOT  = os.path.abspath(CONFIG.get("dev_root", "."))
PLAN_FILE = CONFIG.get("plan_file", "plan.json")
DIRECT_URL = "http://127.0.0.1:8787/v1/chat/completions"
MODEL = "mlx-community/Qwen3.6-27B-4bit"

DECOMP_SYS = (
    "You are a software planner. Given a project goal, output a JSON array of small, ordered, "
    "atomic build tasks. Each object has EXACTLY: \"title\", \"prompt\" (one imperative sentence "
    "for a single change), \"file\" (the ONE file it creates/modifies), \"deps\" (array of other "
    "existing files it must read). Build dependencies first. Output ONLY the JSON array."
)
AGENT_KW = ("integrate", "wire", "connect", " run ", "test", "install", "across files", "end-to-end")
VERIFY = {".js": 'node --check "{f}"', ".mjs": 'node --check "{f}"',
          ".ts": 'npx -y tsc --noEmit "{f}"', ".py": 'python -m py_compile "{f}"'}

def call_model(goal, max_tokens=4096):
    body = json.dumps({"model": MODEL, "temperature": 0.2, "stream": False, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": DECOMP_SYS},
                                    {"role": "user", "content": goal}]}).encode()
    req = urllib.request.Request(DIRECT_URL, data=body, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=1800))["choices"][0]["message"]["content"]

def verify_for(file):
    if not file: return "true"
    _, ext = os.path.splitext(file)
    t = VERIFY.get(ext)
    return (f'test -f "{file}" && ' + t.format(f=file)) if t else f'test -s "{file}"'

def normalize(raw):
    seen, out = set(), []
    for i, t in enumerate(raw, 1):
        file = (t.get("file") or "").strip()
        deps = [d for d in (t.get("deps") or []) if d and d != file]
        prompt = t.get("prompt") or t.get("title") or ""
        first = file not in seen
        if file: seen.add(file)
        agentic = (not file) or any(k in prompt.lower() for k in AGENT_KW)
        task = {"id": str(i), "status": "pending",
                "mode": "agent" if agentic else "direct", "prompt": prompt}
        if agentic:
            task["tools"] = ["Read", "Edit", "Write", "Bash"]
        else:
            task["file"] = file
            task["context"] = ([file] if not first else []) + deps
        task["verify"] = verify_for(file)
        out.append(task)
    return out

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('usage: python -m llmstack.tools.build_plan "high-level project goal"'); sys.exit(1)
    print("🧠 Decomposing goal via local model...")
    raw = call_model(sys.argv[1])
    s, e = raw.find("["), raw.rfind("]")
    tasks = normalize(json.loads(raw[s:e + 1]))
    plan = {"project": sys.argv[1][:60], "tasks": tasks}
    os.makedirs(os.path.dirname(PLAN_FILE) or ".", exist_ok=True)
    json.dump(plan, open(PLAN_FILE, "w"), indent=2)
    print(f"✅ Wrote {len(tasks)} tasks to {PLAN_FILE}:")
    for t in tasks:
        print(f"  {t['id']:>2} [{t['mode']:6}] {t.get('file','-'):14} verify={t['verify'][:40]}")