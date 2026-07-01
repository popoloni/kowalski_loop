import os
import subprocess


class GitManager:
    def __init__(self, dev_root: str):
        self.dev_root = dev_root

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.dev_root,
                              capture_output=True, text=True)

    def ensure_git(self):
        if not os.path.isdir(os.path.join(self.dev_root, ".git")):
            self.git("init", "-q")
        gi = os.path.join(self.dev_root, ".gitignore")
        needed = [".claude/", "node_modules/", "*.log"]
        existing = {l.strip() for l in open(gi, encoding="utf-8")} if os.path.exists(gi) else set()
        missing = [l for l in needed if l not in existing]
        if missing:
            with open(gi, "a", encoding="utf-8") as f:
                f.write("\n".join(missing) + "\n")
        self.git("rm", "-r", "--cached", "-q", "--ignore-unmatch", ".claude")
        self.git("add", ".gitignore")
        if self.git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "Ralph baseline")
        else:
            self.git("commit", "-q", "-m", "Ralph: protect runtime state")
        print("📦 [Ralph] Git ready (last verified state protected).")

    def changed_files(self):
        out = self.git("status", "--porcelain").stdout
        files = set()
        for line in out.splitlines():
            p = line[3:].strip()
            if "->" in p:
                p = p.split("->")[-1].strip()
            files.add(p.strip('"'))
        return files

    def restore_to_checkpoint(self, task=None):
        if self.git("rev-parse", "--verify", "-q", "HEAD").returncode == 0:
            self.git("reset", "--hard", "-q", "HEAD")
            self.git("clean", "-fdq")
        elif task and task.get("file"):
            p = os.path.join(self.dev_root, task["file"])
            if os.path.exists(p):
                os.remove(p)
                print(f"🗑️  [Ralph] No checkpoint yet — removed partial {task['file']}.")

    def git_checkpoint(self, task, label="verified"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"Ralph: task {task.get('id')} {label}")

    def wip_commit(self, task):
        self.git_checkpoint(task, label="WIP (resumable)")
        print(f"💾 [Ralph] Progress on task {task.get('id')} saved (WIP commit).")
