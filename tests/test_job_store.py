import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from src.job_store import JobStore


class JobStoreTest(unittest.TestCase):
    def test_job_lifecycle(self):
        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            job = store.create_job("default", "sender", "复杂分析 test", "test")
            self.assertEqual(job["status"], "queued")

            claimed = store.claim_next_job("agent-1")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["agent_id"], "agent-1")

            store.add_event(job["id"], "progress", "hello")
            completed = store.complete_job(job["id"], True, "done", 0)
            self.assertEqual(completed["status"], "succeeded")
            events = store.list_events(job["id"])
            self.assertEqual([event["event_type"] for event in events], ["claimed", "progress", "complete"])


if __name__ == "__main__":
    unittest.main()
