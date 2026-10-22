"""Bounded IPC between the HTTP process and its sole disk/CD2 worker.

Protocol v1 carries HTTP commands (id, deadline, method, path, body, headers)
and HTTP responses (id, status, body, headers). Snapshots use a separate latest-
value channel, so a blocked command never holds up health/status requests.
"""
from __future__ import annotations

import copy
import multiprocessing
import os
import queue
import secrets
import signal
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = 1
MAX_COMMANDS = 8
KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_worker_lease = None


class WorkerUnavailable(RuntimeError):
    pass


class WorkerTimeout(RuntimeError):
    pass


class WorkerBusy(RuntimeError):
    pass


class WorkerLease:
    """An OS-owned lease: crashed workers release it without stale pid checks."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                if not self.handle.read(1):
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            self.handle.close()
            raise WorkerUnavailable("数据目录已有 worker 正在运行") from exc

    def close(self):
        if not self.handle.closed:
            self.handle.close()


def _latest_put(channel, value):
    try:
        channel.put_nowait(value)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(value)
        except queue.Full:
            pass


def _watch_parent_exit(application, stop):
    """The child must also notice a killed Web process, without working IPC."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return
    parent.join()
    stop.set()
    try:
        application.stop_worker_subprocesses()
    finally:
        if os.name != "nt":
            # worker_main created this isolated group before starting threads.
            # Kill every tool too, including one not yet entered in the set.
            try:
                os.killpg(os.getpid(), KILL_SIGNAL)
            except ProcessLookupError:
                pass
        # Do not run daemon command threads or multiprocessing finalizers once
        # their owner has died. The OS releases the sole-writer lease here.
        os._exit(1)


def worker_main(commands, responses, snapshots, data_dir, initializer=None):
    # Set before importing app; spawning app.py also imports __mp_main__, which
    # has no disk-writing import side effects.
    os.environ["ISO_PACKER_WORKER_CHILD"] = "1"
    if os.name != "nt":
        os.setsid()
    stop = threading.Event()
    import app as application

    application.APP_DIR = Path(data_dir)
    application.CONFIG_PATH = application.APP_DIR / "config.json"
    application.STATE_PATH = application.APP_DIR / "state.json"
    application.LOG_PATH = application.APP_DIR / "iso-packer.log"
    global _worker_lease
    _worker_lease = WorkerLease(application.APP_DIR / "worker.lock")
    application._worker_process_child = True
    threading.Thread(target=_watch_parent_exit, args=(application, stop), daemon=True, name="worker-parent-monitor").start()
    if initializer is not None:
        initializer(application)
    cfg = application.load_config()
    application.set_app_secret(cfg)
    application.load_state()
    application._worker_ipc_ready = True

    # Recovery may touch FUSE. Keep IPC and snapshot publication independent.
    threading.Thread(target=application.start_worker_once, daemon=True, name="worker-startup").start()
    slots = threading.BoundedSemaphore(MAX_COMMANDS)
    config_commands = threading.Lock()

    def publish():
        while not stop.is_set():
            snapshot = application.process_worker_snapshot()
            if snapshot is not None:
                snapshot.update(protocol=PROTOCOL_VERSION, pid=os.getpid(), at=time.time())
                _latest_put(snapshots, snapshot)
            stop.wait(0.2)

    def reply(message):
        # A timed-out/disconnected Web request must never block a worker thread.
        snapshot = application.process_worker_snapshot()
        if snapshot is not None:
            snapshot.update(protocol=PROTOCOL_VERSION, pid=os.getpid(), at=time.time())
            message["snapshot"] = snapshot
        try:
            responses.put(message, timeout=0.1)
        except queue.Full:
            pass

    def execute(command):
        try:
            if command.get("protocol") != PROTOCOL_VERSION:
                raise ValueError("不支持的 worker 协议版本")
            if command.get("deadline", 0) <= time.monotonic():
                reply({"id": command["id"], "error": "expired"})
                return
            # Config read-modify-write routes share a lock. Other controls,
            # especially cancellation, remain usable during slow filesystem IO.
            config_write = command["method"] == "POST" and command["path"].split("?", 1)[0] in {"/settings", "/login", "/api/cd2/upload-control"}
            if config_write:
                config_commands.acquire()
            try:
                if command["deadline"] <= time.monotonic():
                    reply({"id": command["id"], "error": "expired"})
                    return
                with application.app.test_client(use_cookies=False) as client:
                    response = client.open(
                        command["path"], method=command["method"],
                        headers=command["headers"], data=command["body"],
                        base_url=command["base_url"], follow_redirects=False,
                    )
                    reply({
                        "id": command["id"], "status": response.status_code,
                        "headers": list(response.headers), "body": response.get_data(),
                    })
            finally:
                if config_write:
                    config_commands.release()
        except Exception:
            # Never include exception repr: request headers/config can contain
            # credentials and upstream errors may echo them.
            reply({"id": command.get("id"), "error": "failed"})
        finally:
            slots.release()

    threading.Thread(target=publish, daemon=True, name="worker-snapshots").start()
    try:
        while not stop.is_set():
            try:
                command = commands.get(timeout=0.2)
            except queue.Empty:
                continue
            if command.get("shutdown"):
                break
            if not slots.acquire(blocking=False):
                reply({"id": command.get("id"), "error": "busy"})
                continue
            threading.Thread(target=execute, args=(command,), daemon=True, name="worker-command").start()
    finally:
        stop.set()
        application.stop_worker_subprocesses()
        responses.cancel_join_thread()
        snapshots.cancel_join_thread()
        # Keep the lease open until OS process teardown also stops daemon
        # threads. Closing it here would permit another writer too early.


class ProcessWorker:
    """One child process, bounded pending calls, lock-free snapshot consumers."""

    def __init__(self, data_dir: Path, initializer=None):
        self._context = multiprocessing.get_context("spawn")
        self._commands = self._context.Queue(maxsize=MAX_COMMANDS)
        self._responses = self._context.Queue(maxsize=MAX_COMMANDS * 2)
        self._snapshots = self._context.Queue(maxsize=1)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._snapshot = None
        self._closed = False
        self._slots = threading.BoundedSemaphore(MAX_COMMANDS)
        self.process = self._context.Process(
            target=worker_main, args=(self._commands, self._responses, self._snapshots, str(data_dir), initializer),
            name="iso-packer-worker", daemon=True,
        )

    def start(self):
        self.process.start()
        threading.Thread(target=self._receive, daemon=True, name="worker-responses").start()
        threading.Thread(target=self._receive_snapshots, daemon=True, name="web-snapshots").start()
        threading.Thread(target=self._monitor_exit, daemon=True, name="worker-exit-monitor").start()

    def _monitor_exit(self):
        # A killed Queue feeder can leave an incomplete frame in the pipe.
        # Monitor the OS sentinel independently of both queue reader threads.
        self.process.join()
        self._kill_group(KILL_SIGNAL)

    def _kill_group(self, signum):
        if os.name != "nt" and self.process.pid:
            try:
                os.killpg(self.process.pid, signum)
            except ProcessLookupError:
                pass

    def _accept_snapshot(self, snapshot):
        if snapshot and snapshot.get("protocol") == PROTOCOL_VERSION:
            with self._snapshot_lock:
                current = self._snapshot
                if snapshot.get("revision") is not None:
                    newer = not current or current.get("revision") is None or snapshot["revision"] >= current["revision"]
                else:
                    newer = not current or (current.get("revision") is None and snapshot.get("at", 0) >= current.get("at", 0))
                if newer:
                    self._snapshot = snapshot

    def _receive(self):
        while not self._closed:
            try:
                response = self._responses.get(timeout=0.2)
            except queue.Empty:
                if not self.process.is_alive():
                    self._kill_group(KILL_SIGNAL)
                    return
                continue
            except (EOFError, OSError, ValueError):
                return
            with self._pending_lock:
                waiter = self._pending.get(response.get("id"))
            self._accept_snapshot(response.get("snapshot"))
            if waiter is not None:
                try:
                    waiter.put_nowait(response)
                except queue.Full:
                    pass

    def _receive_snapshots(self):
        while not self._closed:
            try:
                snapshot = self._snapshots.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                return
            self._accept_snapshot(snapshot)

    def snapshot(self):
        # A snapshot is assigned atomically and never mutated after publication.
        return copy.deepcopy(self._snapshot) if self._snapshot else None

    def status(self):
        snapshot = self._snapshot or {}
        age = max(0.0, time.time() - snapshot["at"]) if snapshot.get("at") else None
        alive = not self._closed and self.process.is_alive()
        return {
            "mode": "process", "pid": self.process.pid, "alive": alive,
            "ready": bool(alive and snapshot.get("ready")),
            "startup_complete": bool(snapshot.get("startup_complete")),
            "snapshot_at": snapshot.get("at"),
            "snapshot_age_seconds": round(age, 1) if age is not None else None,
            "snapshot_stale": age is None or age > 5,
        }

    def call(self, *, method, path, headers=(), body=b"", base_url="http://localhost", timeout=20):
        if self._closed or not self.process.is_alive():
            raise WorkerUnavailable("worker 未运行，请重启服务")
        if not self._slots.acquire(blocking=False):
            raise WorkerBusy("worker 请求已满，请稍后重试")
        command_id = secrets.token_hex(16)
        waiter = queue.Queue(maxsize=1)
        deadline = time.monotonic() + timeout
        with self._pending_lock:
            self._pending[command_id] = waiter
        try:
            command = {
                "protocol": PROTOCOL_VERSION, "id": command_id, "deadline": deadline,
                "method": method, "path": path, "headers": list(headers),
                "body": body, "base_url": base_url,
            }
            try:
                self._commands.put_nowait(command)
            except queue.Full as exc:
                raise WorkerBusy("worker 请求队列已满，请稍后重试") from exc
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerTimeout("worker 响应超时；已开始的操作可能仍在执行，请查看任务状态后再操作")
                try:
                    response = waiter.get(timeout=min(remaining, 0.2))
                except queue.Empty:
                    if not self.process.is_alive():
                        raise WorkerUnavailable("worker 已退出，请重启服务")
                    continue
                error = response.get("error")
                if error == "busy":
                    raise WorkerBusy("worker 正忙，请稍后重试")
                if error == "expired":
                    raise WorkerTimeout("请求排队超时，尚未执行")
                if error:
                    raise WorkerUnavailable("worker 操作异常，请查看任务状态和日志")
                return response
        finally:
            with self._pending_lock:
                self._pending.pop(command_id, None)
            self._slots.release()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process.is_alive():
            try:
                self._commands.put_nowait({"shutdown": True})
            except queue.Full:
                pass
        self.process.join(timeout=2)
        if self.process.is_alive():
            self._kill_group(signal.SIGTERM)
            self.process.terminate()
            self.process.join(timeout=2)
        self._kill_group(KILL_SIGNAL)
        # Queue feeder threads may still hold a message after child shutdown.
        for channel in (self._commands, self._responses, self._snapshots):
            channel.cancel_join_thread()
            channel.close()
