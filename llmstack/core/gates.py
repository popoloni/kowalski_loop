import os
import re
import subprocess


def changed_files(git_manager):
    return git_manager.changed_files()


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
        print(f"❌ [Ralph] Orphan JS not loaded by index.html: {orphans}")
        return False
    if missing:
        print(f"❌ [Ralph] index.html references missing files: {missing}")
        return False
    return True


def run_smoke(dev_root, task):
    code = task.get("smoke")
    if isinstance(code, list):
        code = "\n".join(code)
    if not code:
        return True
    print("🧪 [Ralph] Running behavioral smoke test...")
    try:
        r = subprocess.run(["node", "-e", code], cwd=dev_root,
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("❌ [Ralph] Smoke test TIMED OUT.")
        return False
    if r.returncode != 0:
        print(f"❌ [Ralph] Smoke FAILED:\n{r.stdout}\n{r.stderr}")
        return False
    print(f"✅ [Ralph] Smoke: {r.stdout.strip()[:200]}")
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
    print("🧑‍⚖️ [Ralph] Review is not enabled in Phase 0; passing by default.")
    return True


def verify_detailed(task, dev_root, git_manager, config, require_change_override=None):
    verify_cmd = task.get("verify")
    if verify_cmd:
        print(f"🔎 [Ralph] Verifying: {verify_cmd}")
        r = subprocess.run(verify_cmd, shell=True, cwd=dev_root, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ [Ralph] Syntax/verify FAILED:\n{r.stdout}\n{r.stderr}")
            return False, "verify_failed"

    expect = task.get("expect") or []
    target = task.get("file")
    if expect and target:
        p = os.path.join(dev_root, target)
        content = (open(p, encoding="utf-8", errors="ignore").read().lower()
                   if os.path.exists(p) else "")
        missing = [s for s in expect if s.lower() not in content]
        if missing:
            print(f"❌ [Ralph] Feature markers MISSING in {target}: {missing}")
            return False, "expect_failed"
        print(f"✅ [Ralph] Feature markers present: {expect}")

    require_change_enabled = (task.get("require_change", config.get("require_change", True))
                              if require_change_override is None else require_change_override)
    if require_change_enabled:
        changed = changed_files(git_manager)
        if not changed:
            print("❌ [Ralph] No file changes detected — task was a no-op.")
            return False, "no_change"
        if target and target not in changed:
            print(f"❌ [Ralph] Declared file '{target}' was NOT modified. Changed: {sorted(changed)}")
            return False, "target_not_changed"
        print(f"📈 [Ralph] Changed files: {sorted(changed)}")

    if config.get("wiring_check", True) and not check_wiring(dev_root):
        return False, "wiring_failed"

    if not run_smoke(dev_root, task):
        return False, "smoke_failed"

    if config.get("review_enabled") and not review(task, dev_root):
        return False, "review_failed"

    if not verify_cmd and not expect and not task.get("smoke"):
        print("⚠️  [Ralph] No verify/expect/smoke for this task — weak gate.")
    return True, "ok"


def verify(task, dev_root, git_manager, config):
    ok, _ = verify_detailed(task, dev_root, git_manager, config)
    return ok
