import json
import os
import shlex
import threading
import time
import sys

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .continuous_mode import ContinuousMode


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, mode):
        self.mode = mode

    def on_created(self, event):
        self.mode.handle_event(getattr(event, "src_path", None), event.is_directory)

    def on_modified(self, event):
        self.mode.handle_event(getattr(event, "src_path", None), event.is_directory)

    def on_moved(self, event):
        self.mode.handle_event(getattr(event, "dest_path", None), event.is_directory)


class WatchMode(ContinuousMode):
    def __init__(self, config, dev_root, plan, git_manager, executor, services):
        watch_config = dict(config)
        watch_config["continuous_queue_file"] = watch_config.get(
            "watch_queue_file",
            watch_config.get("continuous_queue_file", "task_queue.json"),
        )
        watch_config["continuous_poll_seconds"] = watch_config.get(
            "watch_poll_seconds",
            watch_config.get("continuous_poll_seconds", 2),
        )
        super().__init__(watch_config, dev_root, plan, git_manager, executor, services)
        self.watch_root = os.path.abspath(watch_config.get("watch_root") or dev_root)
        self.queue_file = watch_config.get("continuous_queue_file", "task_queue.json")
        self.debounce_seconds = float(watch_config.get("watch_debounce_seconds", 0.5))
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._recent_events = {}
        self._observer = None
        self._started = False
        self._next_task_id = self._compute_next_task_id()
        self._known_mtimes = {}
        self._start_observer()

    def _compute_next_task_id(self):
        max_id = 0
        for task in self.tasks:
            try:
                max_id = max(max_id, int(task.get("id", 0)))
            except (TypeError, ValueError):
                continue
        return max_id + 1

    def _start_observer(self):
        if self._started:
            return
        self._observer = Observer()
        self._observer.daemon = True
        self._observer.schedule(_WatchHandler(self), self.watch_root, recursive=True)
        self._observer.start()
        self._started = True

    def close(self):
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _should_ignore(self, path):
        if not path:
            return True
        abs_path = os.path.abspath(path)
        if abs_path == os.path.abspath(self.queue_file):
            return True
        if not abs_path.endswith(".py"):
            return True
        rel_path = os.path.relpath(abs_path, self.watch_root)
        if rel_path.startswith(".."):
            return True
        parts = set(rel_path.split(os.sep))
        return bool(parts.intersection({".git", "node_modules", "env", "__pycache__", "logs", "old"}))

    def _enqueue_watch_task(self, path):
        if self._should_ignore(path):
            return
        rel_path = os.path.relpath(os.path.abspath(path), self.dev_root)
        abs_path = os.path.abspath(path)
        try:
            self._known_mtimes[rel_path] = os.path.getmtime(abs_path)
        except FileNotFoundError:
            pass
        now = time.time()
        with self._condition:
            last_seen = self._recent_events.get(rel_path, 0.0)
            if now - last_seen < self.debounce_seconds:
                return
            self._recent_events[rel_path] = now

            task = {
                "id": self._next_task_id,
                "title": f"Watch {rel_path}",
                "prompt": (
                    f"The Python file {rel_path} changed. Inspect the current file and apply the "
                    f"necessary lint/fix changes while preserving existing behavior."
                ),
                "file": rel_path,
                "context": [rel_path],
                "strategy": "edit",
                "mode": "agent",
                "verify": f'{shlex.quote(sys.executable)} -m py_compile "{rel_path}"',
            }
            self._next_task_id += 1
            self.tasks.append(task)
            self.plan["tasks"] = self.tasks
            self._persist_plan()
            self._condition.notify_all()

    def _scan_for_changes(self):
        for root, dirs, files in os.walk(self.watch_root):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "env", "__pycache__", "logs", "old"}]
            for name in files:
                if not name.endswith(".py"):
                    continue
                abs_path = os.path.join(root, name)
                if self._should_ignore(abs_path):
                    continue
                rel_path = os.path.relpath(abs_path, self.dev_root)
                try:
                    mtime = os.path.getmtime(abs_path)
                except FileNotFoundError:
                    continue
                previous = self._known_mtimes.get(rel_path)
                if previous is None:
                    self._known_mtimes[rel_path] = mtime
                    continue
                if mtime > previous:
                    self._enqueue_watch_task(abs_path)

    def handle_event(self, path, is_directory):
        if is_directory:
            return
        self._enqueue_watch_task(path)

    def next_task(self):
        while True:
            with self._condition:
                task = self._next_available_task()
                if task is not None:
                    return task
                if self.services.should_stop():
                    return None
                self._condition.wait(timeout=float(self.config.get("watch_poll_seconds", self.poll_seconds)))
            self._scan_for_changes()