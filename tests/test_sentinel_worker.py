"""Offline persistent-worker tests: no wallet, network, deployment or Telegram."""
import json
import tempfile
import unittest
from pathlib import Path

from sentinel_worker import (INTERVALS, Worker, acquire_lock, preflight,
                             seed_volume)


class WorkerTests(unittest.TestCase):
    def env(self, path):
        return {"SENTINEL_WORKER_ENABLED": "true",
                "SENTINEL_GITHUB_WRITER_DISABLED": "true",
                "SENTINEL_STATE_DIR": str(path)}

    def test_worker_refuses_unsafe_missing_persistence_or_overlap_optin(self):
        with tempfile.TemporaryDirectory() as d:
            store = Path(d)
            env = self.env(store)
            self.assertEqual(preflight(env), store)
            bad = dict(env, SENTINEL_WORKER_ENABLED="false")
            with self.assertRaises(RuntimeError):
                preflight(bad)
            bad = dict(env, SENTINEL_GITHUB_WRITER_DISABLED="false")
            with self.assertRaises(RuntimeError):
                preflight(bad)
            bad = dict(env, SENTINEL_STATE_DIR="data")
            with self.assertRaises(RuntimeError):
                preflight(bad)
            bad = dict(env, SENTINEL_STATE_DIR="/no-such-persistent-volume")
            with self.assertRaises(RuntimeError):
                preflight(bad)

    def test_existing_historical_ledger_is_never_overwritten_by_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            source = d / "source"
            storage = d / "volume"
            source.mkdir()
            storage.mkdir()
            from sentinel_worker import STATE_FILES
            for name in STATE_FILES:
                (source / name).write_text(json.dumps({"old": True}))
            seed_volume(storage, source)
            (storage / "paper_state.json").write_text(json.dumps({
                "live_history": ["BONK", "DOGE"]}))
            (source / "paper_state.json").write_text(json.dumps({"new": True}))
            seed_volume(storage, source)
            self.assertEqual(json.loads((storage / "paper_state.json").read_text()),
                             {"live_history": ["BONK", "DOGE"]})

    def test_single_writer_lock_prevents_concurrent_second_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            volume = Path(tmp)
            handle = acquire_lock(volume)
            try:
                with self.assertRaises(RuntimeError):
                    acquire_lock(volume)
            finally:
                handle.close()
            other = acquire_lock(volume)
            other.close()

    def test_worker_runs_at_interval_records_heartbeat_and_no_duplicate_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits = []
            now = [1]
            worker = Worker(Path(tmp),
                            tasks={"coinbase_paper": lambda: hits.append("paper")},
                            clock=lambda: now[0])
            worker.cycle()
            worker.cycle()
            self.assertEqual(hits, ["paper"])
            now[0] += INTERVALS["coinbase_paper"] - 1
            worker.cycle()
            self.assertEqual(len(hits), 1)
            now[0] += 1
            worker.cycle()
            self.assertEqual(len(hits), 2)
            hb = json.loads((Path(tmp) / "worker_heartbeat.json").read_text())
            self.assertEqual(hb["tasks"]["coinbase_paper"]["status"], "ok")

    def test_task_failure_is_logged_without_fake_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fails():
                raise ValueError("no public quote")
            worker = Worker(Path(tmp), tasks={"coinbase_paper": fails},
                            clock=lambda: 50)
            health = worker.cycle()
            self.assertEqual(health["tasks"]["coinbase_paper"]["status"], "error")
            self.assertEqual(health["tasks"]["coinbase_paper"]["error_type"], "ValueError")
            self.assertIsNone(health["tasks"]["coinbase_paper"]["last_success_utc"])


if __name__ == "__main__":
    unittest.main()
