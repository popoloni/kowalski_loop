import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request

from llmstack.config import DEFAULT_CONFIG, normalize_permission_mode, normalize_thinking_mode
from llmstack.core.gates import verify

MAX_CONTINUATIONS = 6


class Executor:
    def __init__(self, config, dev_root, git_manager, debug_log=None, debug_max=0,
                 health_url=None,
                 model_name="active-model",
                 model_target=None,
                 direct_url=None):
        self.config = config
        self.dev_root = dev_root
        self.git_manager = git_manager
        self.debug_log = debug_log
        self.debug_max = debug_max
        default_inference_url = f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['inference_port']}/v1/models"
        self.health_url = health_url or self.config.get("inference_health_url", default_inference_url)
        self.model_name = model_name
        self.model_target = model_target or "mlx-community/Qwen3.6-27B-4bit"
        default_headroom_url = f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['headroom_port']}/v1/chat/completions"
        default_inference_chat_url = f"http://{DEFAULT_CONFIG['local_host']}:{DEFAULT_CONFIG['inference_port']}/v1/chat/completions"
        self.direct_url = direct_url or self.config.get("headroom_chat_url", default_headroom_url) or self.config.get("inference_chat_url", default_inference_chat_url)

    def _dbg(self, label, payload):
        if not self.debug_log:
            return
        if not isinstance(payload, str):
            try:
                payload = json.dumps(payload, indent=2, ensure_ascii=False)
            except Exception:
                payload = str(payload)
        if self.debug_max and len(payload) > self.debug_max:
            payload = payload[:self.debug_max] + f"\n...[truncated {len(payload) - self.debug_max} chars]"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.debug_log, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 90}\n[{ts}] {label}\n{'-' * 90}\n{payload}\n")

    def _agent_transcript(self, data):
        """Return a compact transcript string safe for debug logging."""
        if isinstance(data, dict):
            return json.dumps(data, indent=2, ensure_ascii=False)
        if isinstance(data, list):
            parts = []
            for i, msg in enumerate(data, 1):
                if not isinstance(msg, dict):
                    parts.append(f"[{i}] {msg}")
                    continue
                mtype = msg.get("type", "unknown")
                subtype = msg.get("subtype", "")
                payload = msg.get("result") or msg.get("error") or msg.get("message") or ""
                if isinstance(payload, (dict, list)):
                    payload = json.dumps(payload, ensure_ascii=False)
                payload = str(payload).replace("\n", " ").strip()
                if len(payload) > 400:
                    payload = payload[:400] + "...[truncated]"
                tag = f"{mtype}/{subtype}" if subtype else mtype
                parts.append(f"[{i}] {tag}: {payload}")
            return "\n".join(parts)
        return str(data)

    def _is_content_block_error(self, text):
        low = (text or "").lower()
        return "content block is not a text block" in low

    def _extract_kowalski_status(self, text):
        if not text:
            return None
        m = re.search(r"KowalskiStatus\s*:\s*(changed|already_done|blocked)", text, flags=re.IGNORECASE)
        return m.group(1).lower() if m else None

    def _strip_fences(self, text):
        t = (text or "").strip()
        # Prefer the first fenced block if present anywhere in the response.
        m = re.search(r"```(?:[a-zA-Z0-9_+.-]+)?\n([\s\S]*?)\n```", t)
        if m:
            t = m.group(1)
        else:
            # If no complete block exists, drop standalone fence marker lines.
            t = re.sub(r"(?m)^\s*```(?:[a-zA-Z0-9_+.-]+)?\s*$", "", t)
        return t.strip() + "\n"

    def _detect_extreme_direct_degeneracy(self, code):
        """Detect only extreme output corruption patterns to avoid false positives."""
        text = code or ""
        if len(text) < 12000:
            return None

        # 1) Very long single-character runs (e.g., zzzzz....)
        run = re.search(r"(.)\1{511,}", text)
        if run:
            ch = run.group(1)
            return f"extreme repeated character run detected ('{ch}' x512+)"

        # 2) Repeated long token chunks with very high count.
        # Conservative threshold to avoid valid repetitive code/data.
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{7,}", text)
        if tokens:
            counts = {}
            for tok in tokens:
                counts[tok] = counts.get(tok, 0) + 1
            top_tok, top_count = max(counts.items(), key=lambda kv: kv[1])
            if top_count >= 140:
                return f"extreme repeated identifier detected ('{top_tok}' repeated {top_count} times)"

        # 3) Very low lexical diversity combined with huge payload.
        # Apply only on large files to reduce false positives.
        if len(tokens) >= 200:
            unique_ratio = len(set(tokens)) / float(len(tokens))
            if unique_ratio < 0.06:
                return f"very low token diversity detected (unique ratio={unique_ratio:.3f})"

        return None

    def _retry_feedback_note(self, task):
        feedback = (task.get("_verify_feedback") or "").strip()
        if not feedback:
            return ""
        return (
            "\n\nThe previous attempt FAILED verification with:\n"
            f"{feedback[:1200]}\n"
            "Fix exactly this."
        )

    def _thinking_mode_for_task(self, task):
        return normalize_thinking_mode(task.get("thinking_mode", self.config.get("thinking_mode")))

    def _apply_thinking_mode(self, env, thinking_mode):
        if thinking_mode == "off":
            env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] = "1"
            env["CLAUDE_CODE_DISABLE_THINKING"] = "1"
        elif thinking_mode == "auto":
            env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] = "0"
            env["CLAUDE_CODE_DISABLE_THINKING"] = "1"
        elif thinking_mode == "on":
            env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] = "0"
            env["CLAUDE_CODE_DISABLE_THINKING"] = "0"
        else:
            raise ValueError(f"Unsupported thinking_mode '{thinking_mode}'")
        return env

    def _agent_env(self, task):
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        timeout_ms = str(int(self.config["task_timeout"] * 1000))
        env.update({
            "API_TIMEOUT_MS": timeout_ms,
            "CLAUDE_STREAM_IDLE_TIMEOUT_MS": timeout_ms,
            "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
            "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
        })
        thinking_mode = self._thinking_mode_for_task(task)
        self._apply_thinking_mode(env, thinking_mode)
        return env

    def _post_chat(self, messages, max_tokens):
        body = json.dumps({"model": self.model_target, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.2, "stream": False}).encode()
        req = urllib.request.Request(self.direct_url, data=body, headers={"Content-Type": "application/json"})
        resp = json.load(urllib.request.urlopen(req, timeout=self.config["task_timeout"]))
        choice = resp["choices"][0]
        return (choice["message"]["content"] or ""), choice.get("finish_reason", "stop")

    def _ping(self, timeout=3):
        try:
            return urllib.request.urlopen(self.health_url, timeout=timeout).getcode() == 200
        except Exception:
            return False

    def _watch_during_task(self, proc, server_crashed):
        fails = 0
        while proc.poll() is None:
            if not self._ping():
                fails += 1
                if fails >= 3:
                    print("🔥 [Kowalski] DFlash died DURING the task — aborting agent.")
                    server_crashed.set()
                    self._kill_proc(proc)
                    return
            else:
                fails = 0
            time.sleep(3)

    def _kill_proc(self, proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass

    def choose_executor(self, task):
        if task.get("mode") != "direct":
            return "agent"
        strategy = task.get("strategy")
        if strategy == "edit":
            return "agent"
        if strategy == "rewrite":
            return "direct"
        file = task.get("file")
        if file and file in task.get("context", []):
            p = os.path.join(self.dev_root, file)
            if os.path.exists(p) and os.path.getsize(p) > self.config["size_threshold_bytes"]:
                return "agent"
        return "direct"

    def syntax_ok(self, task):
        f = task.get("file")
        if not f:
            return True
        p = os.path.join(self.dev_root, f)
        if not os.path.exists(p):
            return True
        if f.endswith((".js", ".mjs")):
            return subprocess.run(["node", "--check", f], cwd=self.dev_root,
                                  capture_output=True).returncode == 0
        return True

    def run_direct_task(self, task, attempt=1):
        out_file = task["file"]
        context = task.get("context", [])
        ctx = ""
        for cf in context:
            p = os.path.join(self.dev_root, cf)
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="ignore") as f:
                    ctx += f"\n\n--- existing {cf} ---\n{f.read()}"
        user = task["prompt"]
        if ctx:
            user += f"\n\nRelevant existing files:{ctx}"
        if out_file in context:
            user += (f"\n\nYou are MODIFYING {out_file}: preserve ALL existing functionality "
                     f"and add the requested behavior. Output the COMPLETE updated file.")
        if attempt > 1:
            user += ("\n\nNOTE: the previous attempt produced invalid/truncated code. "
                     "Produce the COMPLETE, syntactically valid file this time.")
        user += self._retry_feedback_note(task)
        user += f"\n\nOutput ONLY the complete contents of {out_file}. No markdown fences, no commentary."

        messages = [
            {"role": "system", "content": "You are a precise code generator. Output only raw, valid file contents."},
            {"role": "user", "content": user},
        ]
        max_tokens = task.get("max_tokens", 8192)
        print(
            f"✍️  [Kowalski] Direct-generating {out_file} using model '{self.model_name}' "
            f"(context: {context or 'none'})"
        )
        self._dbg(f"DIRECT INPUT · task {task.get('id')} · attempt {attempt}", messages)

        full = ""
        for rnd in range(MAX_CONTINUATIONS):
            try:
                piece, finish = self._post_chat(messages, max_tokens)
            except Exception as e:
                print(f"❌ [Kowalski] Direct call failed: {e}")
                return "TIMEOUT"
            self._dbg(f"DIRECT OUTPUT · task {task.get('id')} · round {rnd + 1} · finish={finish}", piece)
            full += piece
            if finish != "length":
                break
            print(f"   ↪︎ hit token cap — asking model to CONTINUE (round {rnd + 1})...")
            messages.append({"role": "assistant", "content": piece})
            messages.append({"role": "user", "content":
                "Continue the file from EXACTLY where you stopped. Do NOT repeat any previous "
                "lines, do NOT add fences or commentary — output only the remaining raw content."})
        else:
            print("⚠️  [Kowalski] Still truncated after continuations; writing partial (verify will catch it).")

        code = self._strip_fences(full)
        degeneracy_reason = self._detect_extreme_direct_degeneracy(code)
        if degeneracy_reason:
            msg = (
                "Direct output appears severely degenerate/corrupted and was rejected before write: "
                f"{degeneracy_reason}. Regenerate the full file cleanly from scratch; no repeated filler text."
            )
            print(f"⚠️  [Kowalski] {msg}")
            task["_verify_feedback"] = msg
            return "VERIFY_FAILED"

        output_path = os.path.join(self.dev_root, out_file)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"📝 [Kowalski] Wrote {out_file} ({len(code)} bytes).")
        return "OK" if verify(task, self.dev_root, self.git_manager, self.config) else "VERIFY_FAILED"

    def run_direct_context_fallback(self, task, attempt=1):
        # Best-effort fallback when agent transport/format keeps failing.
        # Regenerate only the task target file; context files remain read-only input.
        out_file = task.get("file")
        if not out_file:
            return "AGENT_ERROR"

        subtask = dict(task)
        subtask["file"] = out_file
        subtask["verify"] = None
        subtask["prompt"] = (
            f"{task.get('prompt', '').strip()}\n\n"
            "Fallback mode due to repeated agent format errors. "
            f"Focus ONLY on {out_file}. Keep all unrelated behavior unchanged. "
            f"Use context files only as references; do not rewrite them. "
            f"If {out_file} already satisfies the requirement, return its equivalent complete file."
        )
        print(f"🛟 [Kowalski] Direct fallback on {out_file}...")
        out = self.run_direct_task(subtask, attempt=attempt)
        if out == "TIMEOUT":
            return "TIMEOUT"

        return "OK" if verify(task, self.dev_root, self.git_manager, self.config) else "VERIFY_FAILED"

    def execute_task(self, task, attempt=1, resuming=False):
        prompt = task["prompt"]
        file = task.get("file")
        sys_prompt = self.config.get("strict_sys_prompt") or (
            "You drive a coding agent through a translation proxy that FAILS if a single "
            "assistant message mixes prose and tool calls. Rules:\n"
            "1. Do NOT narrate.\n"
            "2. NEVER write text AFTER a tool call in the same response.\n"
            "3. Prefer ONE tool call per response.\n"
            "4. For file-creation, write the file directly; do NOT read other files unless required.\n"
            "5. Do only the single atomic task, then stop."
        )
        sys_prompt += (
            "\nFORMAT SAFETY:\n"
            "- Output only plain text tool protocol messages compatible with Claude Code.\n"
            "- Do not emit non-text content blocks, JSON wrappers, XML tags, or markdown wrappers.\n"
            "- If unsure, respond with a single minimal valid action in plain text.\n"
            "- In your final plain-text result include exactly one status line: "
            "KowalskiStatus: changed OR KowalskiStatus: already_done OR KowalskiStatus: blocked."
        )
        if file:
            sys_prompt += (f" Use the Edit tool to make minimal, targeted changes to {file}; "
                           f"preserve all unrelated code and do NOT rewrite the whole file.")
        if resuming:
            sys_prompt += (f" IMPORTANT: {file or 'the file'} ALREADY contains partial work for this "
                           f"task from a previous run. CONTINUE and COMPLETE it — do not restart from "
                           f"scratch and do not duplicate code that is already there.")
        sys_prompt += self._retry_feedback_note(task)
        thinking_mode = self._thinking_mode_for_task(task)
        tools = task.get("tools") or self.config.get("agent_tools") or ["Read", "Edit"]
        permission_mode = normalize_permission_mode(task.get("permission_mode", self.config["permission_mode"]))
        cmd = ["ccr", "code", "-p", prompt, "--output-format", "json",
               "--permission-mode", permission_mode,
               "--max-turns", str(self.config["max_turns"]),
               "--append-system-prompt", sys_prompt]
        if tools:
            cmd += ["--allowedTools", *tools]
        cmd += ["--disallowedTools", "Bash", "Glob", "Grep", "WebFetch", "Task"]

        env = self._agent_env(task)

        format_retries = int(self.config.get("agent_format_retries", 2))
        recovery_prompt = (
            "RECOVERY MODE: previous attempt failed due to non-text content block formatting. "
            "From now on emit ONLY plain text messages compatible with Claude Code tool protocol. "
            "Never emit structured content blocks, XML/JSON wrappers, markdown fences, or rich blocks."
        )

        print(f"⚙️  [Kowalski] Running Task {task.get('id')} (agentic, turns={self.config['max_turns']}) in {self.dev_root}")
        self._dbg(
            f"AGENT INPUT · task {task.get('id')} · attempt {attempt} · resuming={resuming}",
            f"PROMPT:\n{prompt}\n\nAPPENDED SYSTEM PROMPT:\n{sys_prompt}\n\n"
            f"ALLOWED TOOLS: {tools}\nPERMISSION_MODE: {permission_mode}\nTHINKING_MODE: {thinking_mode}\n"
            f"MAX_TURNS: {self.config['max_turns']}\n"
            f"(Claude Code's full base system prompt + tool defs + file reads are NOT shown here — "
            f"see headroom_traffic.jsonl for the literal on-wire prompt.)")

        for fmt_try in range(format_retries + 1):
            run_cmd = list(cmd)
            if fmt_try > 0:
                run_cmd += ["--append-system-prompt", recovery_prompt]
                print(f"↻ [Kowalski] Retrying task {task.get('id')} with format-safe prompt ({fmt_try}/{format_retries})...")

            server_crashed = threading.Event()
            proc = subprocess.Popen(run_cmd, cwd=self.dev_root, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, preexec_fn=os.setsid)
            threading.Thread(target=self._watch_during_task, args=(proc, server_crashed), daemon=True).start()
            try:
                out, err = proc.communicate(timeout=self.config["task_timeout"])
            except subprocess.TimeoutExpired:
                self._kill_proc(proc)
                return "TIMEOUT"

            if server_crashed.is_set():
                return "SERVER_CRASH"

            outcome = self._evaluate(out, err, task)
            if outcome == "FORMAT_ERROR" and fmt_try < format_retries:
                continue
            if outcome == "FORMAT_ERROR":
                return "FORMAT_ERROR"
            return outcome

        return "FORMAT_ERROR"

    def _evaluate(self, stdout, stderr, task):
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            self._dbg(f"AGENT OUTPUT (unparseable) · task {task.get('id')}", (stdout or stderr or "<empty>"))
            if self._is_content_block_error(stdout or "") or self._is_content_block_error(stderr or ""):
                print("ℹ️  [Kowalski] Detected non-text content-block formatting error from provider.")
                return "FORMAT_ERROR"
            print("❌ [Kowalski] Could not parse CLI JSON:", (stdout or stderr or "<empty>")[:300])
            return "BAD_OUTPUT"

        self._dbg(f"AGENT OUTPUT · task {task.get('id')}", self._agent_transcript(data))

        result = None
        if isinstance(data, list):
            for msg in data:
                if isinstance(msg, dict) and msg.get("type") == "result":
                    result = msg
        elif isinstance(data, dict):
            result = data
        if not result:
            return "BAD_OUTPUT"

        subtype = result.get("subtype")
        is_error = bool(result.get("is_error"))
        detail = result.get("result") or result.get("error") or ""
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)
        detail = str(detail)
        kowalski_status = self._extract_kowalski_status(detail)

        if kowalski_status == "blocked":
            print("ℹ️  [Kowalski] Agent reported KowalskiStatus: blocked")
            return "AGENT_ERROR"

        if kowalski_status == "already_done" and (not is_error) and subtype == "success":
            print("ℹ️  [Kowalski] Agent reported KowalskiStatus: already_done")
            return "ALREADY_DONE"

        if subtype in ("error_max_turns", "error_during_execution"):
            print(f"ℹ️  [Kowalski] subtype={subtype}. Detail: {detail[:200]}")
            return "AGENT_ERROR"

        if is_error or subtype != "success":
            print(f"ℹ️  [Kowalski] DIRTY finish: is_error={is_error}, subtype={subtype}. Detail: {detail[:200]}")
            low = detail.lower()
            if "tim" in low and "out" in low:
                return "TIMEOUT"
            if self._is_content_block_error(low):
                return "FORMAT_ERROR"
            return "AGENT_ERROR"

        return "OK" if verify(task, self.dev_root, self.git_manager, self.config) else "VERIFY_FAILED"
