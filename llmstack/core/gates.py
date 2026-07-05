import fnmatch
import os
import re
import subprocess


def changed_files(git_manager):
    return git_manager.changed_files()


def _target_present_in_changed(target, changed):
    if target in changed:
        return True
    norm_target = target.rstrip("/")
    for path in changed:
        norm_path = path.rstrip("/")
        if not norm_path:
            continue
        # Accept both "target under changed dir" and "changed file under target dir".
        if norm_target.startswith(norm_path + "/") or norm_path.startswith(norm_target + "/"):
            return True
    return False


def check_wiring(dev_root):
    idx = os.path.join(dev_root, "index.html")
    if not os.path.exists(idx):
        return True
    html = open(idx, encoding="utf-8", errors="ignore").read()
    refs = [os.path.basename(r) for r in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)]
    js_files = [f for f in os.listdir(dev_root)
                if f.endswith(".js") and not f.startswith(".") and "test" not in f.lower()]
    orphans = [f for f in js_files if f not in refs]
    missing = [r for r in refs if r.endswith(".js") and not os.path.exists(os.path.join(dev_root, r))]
    if orphans:
        print(f"❌ [Kowalski] Orphan JS not loaded by index.html: {orphans}")
        return False
    if missing:
        print(f"❌ [Kowalski] index.html references missing files: {missing}")
        return False
    return True


def run_smoke(dev_root, task):
    code = task.get("smoke")
    if isinstance(code, list):
        code = "\n".join(code)
    if not code:
        return True
    print("🧪 [Kowalski] Running behavioral smoke test...")
    try:
        r = subprocess.run(["node", "-e", code], cwd=dev_root,
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("❌ [Kowalski] Smoke test TIMED OUT.")
        return False
    if r.returncode != 0:
        print(f"❌ [Kowalski] Smoke FAILED:\n{r.stdout}\n{r.stderr}")
        return False
    print(f"✅ [Kowalski] Smoke: {r.stdout.strip()[:200]}")
    return True


def syntax_ok(dev_root, task):
    f = task.get("file")
    if not f:
        return True
    p = os.path.join(dev_root, f)
    if not os.path.exists(p):
        return True
    if f.endswith((".js", ".mjs")):
        return subprocess.run(["node", "--check", f], cwd=dev_root,
                              capture_output=True).returncode == 0
    return True


def review(task, dev_root):
    print("🧑‍⚖️ [Kowalski] Review is not enabled in Phase 0; passing by default.")
    return True


def _gate_spec(name, kind, **data):
    spec = {"name": name, "kind": kind}
    spec.update(data)
    return spec


def _task_plugin_names(task, key):
    raw = task.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"task['{key}'] must be a list of non-empty plugin names")
    return {item.strip() for item in raw}


def _plugin_feedback(name, result):
    parts = []
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    payload = "\n\n".join(parts) if parts else f"exit code {result.returncode}"
    return f"Verification plugin '{name}' failed.\n{payload}"


def _plugin_applies(name, plugin, task, when):
    if not plugin.get("enabled", True) or plugin.get("when") != when:
        return False

    allowed = _task_plugin_names(task, "verification_plugins")
    disabled = _task_plugin_names(task, "disable_plugins") or set()
    if name in disabled:
        return False
    if allowed is not None and name not in allowed:
        return False

    target = task.get("file") or ""
    if plugin.get("languages"):
        ext = os.path.splitext(target)[1].lower()
        if ext not in {item.lower() for item in plugin["languages"]}:
            return False

    if plugin.get("files"):
        if not target or not any(fnmatch.fnmatch(target, pattern) for pattern in plugin["files"]):
            return False

    return True


def _plugin_gate_specs(task, config, when):
    plugins = config.get("verification_plugins") or {}
    specs = []
    for name, plugin in plugins.items():
        if not _plugin_applies(name, plugin, task, when):
            continue
        specs.append(_gate_spec(
            name=f"plugin:{name}",
            kind="plugin",
            plugin_name=name,
            command=plugin["command"],
            on_failure=plugin.get("on_failure", "fail"),
            when=when,
        ))
    return specs


def build_task_gate_specs(task, config, require_change_override=None):
    specs = []
    verify_cmd = task.get("verify")
    expect = task.get("expect") or []
    target = task.get("file")
    require_change_enabled = (task.get("require_change", config.get("require_change", True))
                              if require_change_override is None else require_change_override)

    if verify_cmd:
        specs.append(_gate_spec("verify", "verify", command=verify_cmd))

    if expect and target:
        specs.append(_gate_spec("expect", "expect", expect=expect, target=target))

    if require_change_enabled:
        specs.append(_gate_spec("require_change", "require_change", target=target))

    if config.get("wiring_check", True):
        specs.append(_gate_spec("wiring", "wiring"))

    if task.get("smoke"):
        specs.append(_gate_spec("smoke", "smoke"))

    specs.extend(_plugin_gate_specs(task, config, when="task"))

    if config.get("review_enabled"):
        specs.append(_gate_spec("review", "review"))

    return specs


def build_plan_complete_gate_specs(task, config):
    return _plugin_gate_specs(task, config, when="plan_complete")


def _run_gate_spec(spec, task, dev_root, git_manager):
    kind = spec["kind"]

    if kind == "verify":
        command = spec["command"]
        print(f"🔎 [Kowalski] Verifying: {command}")
        result = subprocess.run(command, shell=True, cwd=dev_root, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ [Kowalski] Syntax/verify FAILED:\n{result.stdout}\n{result.stderr}")
            feedback = (result.stderr or result.stdout or "").strip()
            return False, "verify_failed", feedback, True
        return True, "ok", "", True

    if kind == "expect":
        target = spec["target"]
        expect = spec["expect"]
        path = os.path.join(dev_root, target)
        content = (open(path, encoding="utf-8", errors="ignore").read().lower()
                   if os.path.exists(path) else "")
        missing = [marker for marker in expect if marker.lower() not in content]
        if missing:
            print(f"❌ [Kowalski] Feature markers MISSING in {target}: {missing}")
            return False, "expect_failed", f"Missing feature markers in {target}: {missing}", True
        print(f"✅ [Kowalski] Feature markers present: {expect}")
        return True, "ok", "", True

    if kind == "require_change":
        changed = changed_files(git_manager)
        if not changed:
            print("❌ [Kowalski] No file changes detected — task was a no-op.")
            return False, "no_change", "No file changes detected during verification.", True
        target = spec.get("target")
        if target and not _target_present_in_changed(target, changed):
            print(f"❌ [Kowalski] Declared file '{target}' was NOT modified. Changed: {sorted(changed)}")
            return False, "target_not_changed", f"Declared file '{target}' was not modified. Changed: {sorted(changed)}", True
        print(f"📈 [Kowalski] Changed files: {sorted(changed)}")
        return True, "ok", "", True

    if kind == "wiring":
        if not check_wiring(dev_root):
            return False, "wiring_failed", "Wiring check failed.", True
        return True, "ok", "", True

    if kind == "smoke":
        if not run_smoke(dev_root, task):
            return False, "smoke_failed", "Smoke test failed.", True
        return True, "ok", "", True

    if kind == "plugin":
        command = spec["command"].format(
            file=task.get("file", ""),
            dev_root=dev_root,
            plan_file=task.get("_plan_file", ""),
        )
        plugin_name = spec["plugin_name"]
        print(f"🧩 [Kowalski] Plugin '{plugin_name}': {command}")
        result = subprocess.run(command, shell=True, cwd=dev_root, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ [Kowalski] Plugin '{plugin_name}' passed.")
            return True, "ok", "", True
        feedback = _plugin_feedback(plugin_name, result)
        if spec.get("on_failure", "fail") == "warn":
            print(f"⚠️  [Kowalski] {feedback}")
            return True, "ok", "", True
        print(f"❌ [Kowalski] {feedback}")
        return False, "plugin_failed", feedback, True

    if kind == "review":
        if not review(task, dev_root):
            return False, "review_failed", "Review gate failed.", True
        return True, "ok", "", True

    raise ValueError(f"Unknown gate kind '{kind}'")


def run_gate_specs(gate_specs, task, dev_root, git_manager):
    ran_any = False
    for spec in gate_specs:
        ok, reason, feedback, ran = _run_gate_spec(spec, task, dev_root, git_manager)
        ran_any = ran_any or ran
        if not ok:
            return False, reason, feedback, ran_any
    return True, "ok", "", ran_any


def run_verification_plugins(task, dev_root, config, when="task"):
    plugin_task = dict(task)
    plugin_task["_plan_file"] = config.get("plan_file", "")
    gate_specs = _plugin_gate_specs(plugin_task, config, when=when)
    return run_gate_specs(gate_specs, plugin_task, dev_root, git_manager=None)


def run_plan_complete_plugins(dev_root, config):
    task = {"id": "plan_complete", "_plan_file": config.get("plan_file", "")}
    return run_gate_specs(build_plan_complete_gate_specs(task, config), task, dev_root, git_manager=None)


def verify_detailed(task, dev_root, git_manager, config, require_change_override=None):
    gate_task = dict(task)
    gate_task["_plan_file"] = config.get("plan_file", "")
    gate_specs = build_task_gate_specs(gate_task, config, require_change_override=require_change_override)
    ok, reason, feedback, ran_any = run_gate_specs(gate_specs, gate_task, dev_root, git_manager)
    if not ok:
        return False, reason, feedback

    if not ran_any:
        print("⚠️  [Kowalski] No verify/expect/smoke for this task — weak gate.")
    return True, "ok", ""


def verify(task, dev_root, git_manager, config):
    ok, _, feedback = verify_detailed(task, dev_root, git_manager, config)
    if ok:
        task.pop("_verify_feedback", None)
    elif feedback:
        task["_verify_feedback"] = feedback
    return ok
