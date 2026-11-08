"""Single-writer, persistent paper-monitor worker for a long-running host.

This replaces GitHub's best-effort schedule ONLY AFTER the operator explicitly
disables GitHub's state writer and mounts persistent storage. No exchange
credentials, wallet signing, actual Coinbase orders, or real DEX trades.

Do NOT launch concurrently with scheduled GitHub state writes.
"""
import argparse
import fcntl
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("sentinel.worker")
SOURCE = Path(__file__).resolve().parent / "data"
STATE_FILES = (
    "paper_state.json", "state.json", "new_launch_radar.json",
    "solana_secondary.json",
    "dex_shadow_state.json", "dex_security_reviews.json", "dex_quote_health.json",
)
INTERVALS = {
    "coinbase_catalog": 6 * 3600,
    "solana_secondary": 3 * 60,
    "launch_research": 3 * 60,
    "route_health": 5 * 60,
    "dex_shadow": 3 * 60,
    "coinbase_paper": 60,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def preflight(env=None, path=None):
    env = os.environ if env is None else env
    if env.get("SENTINEL_WORKER_ENABLED") != "true":
        raise RuntimeError("Worker disabled; set SENTINEL_WORKER_ENABLED=true explicitly")
    if env.get("SENTINEL_GITHUB_WRITER_DISABLED") != "true":
        raise RuntimeError("Refusing dual-writer state risk: first disable GitHub workflow "
                           "writer with repo variable SENTINEL_WORKER_ACTIVE=true, "
                           "then set SENTINEL_GITHUB_WRITER_DISABLED=true")
    value = env.get("SENTINEL_STATE_DIR")
    if not value or not Path(value).is_absolute() or value == "/":
        raise RuntimeError("SENTINEL_STATE_DIR must be an absolute persistent volume path")
    store = Path(value) if path is None else Path(path)
    if not store.exists() or not store.is_dir():
        raise RuntimeError("Persistent state volume is missing; refusing to start")
    if not os.access(store, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError("Persistent state volume is not writable")
    return store


def seed_volume(store, source=SOURCE):
    """Copy existing paper ledger ONCE, NEVER reset it on deployment/restart."""
    for name in STATE_FILES:
        target = store / name
        if target.exists():
            # Corrupt existing ledger is an error; NEVER replace it with repo copy.
            with target.open(encoding="utf-8") as fp:
                json.load(fp)
            continue
        original = source / name
        if not original.exists():
            raise RuntimeError("Missing source ledger: " + name)
        with original.open(encoding="utf-8") as fp:
            json.load(fp)
        temporary = store / (name + ".initializing")
        shutil.copyfile(original, temporary)
        temporary.replace(target)


def acquire_lock(store):
    """A second process/replica must not write the same portfolio."""
    handle = (store / ".single_writer.lock").open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another Trading Sentinel worker owns this state volume") from None
    return handle


def _save_heartbeat(store, health):
    path = store / "worker_heartbeat.json"
    temporary = store / "worker_heartbeat.json.tmp"
    temporary.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def default_tasks():
    # Imported only AFTER env preflight because paths are resolved on import.
    from scanner import run as coinbase_catalog
    from solana_launch_feed import run as solana_secondary
    from new_launch_radar import run as launch_research
    from dex_quote_health import run as route_health
    from dex_shadow import run_once as dex_shadow
    from paper_alerts import scan_once as coinbase_paper
    return {
        "coinbase_catalog": coinbase_catalog,
        "solana_secondary": solana_secondary,
        "launch_research": launch_research,
        "route_health": route_health,
        "dex_shadow": dex_shadow,
        "coinbase_paper": coinbase_paper,
    }


class Worker:
    def __init__(self, store, tasks=None, clock=None):
        self.store = Path(store)
        self.clock = clock or time.monotonic
        self.tasks = tasks or default_tasks()
        self.last = {}
        self.health = {"mode": "READ_ONLY_RESEARCH_AND_PAPER", "started_utc": _now_iso(),
                       "last_cycle_utc": "", "tasks": {},
                       "reminder": "No wallet access, no real trading, no guaranteed stops."}

    def cycle(self, force=False):
        """Single-threaded sequential ticks; nontrading exceptions are recorded."""
        for name, interval in INTERVALS.items():
            if name not in self.tasks:
                continue
            now = self.clock()
            if not force and now - self.last.get(name, float("-inf")) < interval:
                continue
            self.last[name] = now
            try:
                self.tasks[name]()
                self.health["tasks"][name] = {
                    "status": "ok", "last_attempt_utc": _now_iso(),
                    "last_success_utc": _now_iso(),
                }
                LOG.info("WORKER TASK %s completed (no real orders)", name)
            except Exception as exc:
                old = self.health["tasks"].get(name, {})
                self.health["tasks"][name] = {
                    "status": "error", "last_attempt_utc": _now_iso(),
                    "last_success_utc": old.get("last_success_utc"),
                    "error_type": type(exc).__name__,
                }
                # Avoid logging sensitive provider URL/body, Telegram token or key.
                LOG.error("WORKER TASK %s failed (%s)", name, type(exc).__name__)
        self.health["last_cycle_utc"] = _now_iso()
        _save_heartbeat(self.store, self.health)
        return self.health


def main(argv=None):
    parser = argparse.ArgumentParser(description="Persistent research/paper-only worker")
    parser.add_argument("--once", action="store_true",
                        help="Run one complete tick in an explicitly configured volume")
    args = parser.parse_args(argv)
    store = preflight()
    lock = acquire_lock(store)
    try:
        seed_volume(store)
        worker = Worker(store)
        LOG.info("PERSISTENT PAPER WORKER STARTED. No real orders. "
                 "Keep GitHub writer disabled; 1 replica only.")
        while True:
            worker.cycle()
            if args.once:
                break
            time.sleep(5)
    finally:
        lock.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
