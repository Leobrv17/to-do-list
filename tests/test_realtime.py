"""Integration test: two backend processes connected to a dedicated test database.

Install backend/requirements.txt and httpx, then set TEST_DATABASE_URL to a
PostgreSQL SQLAlchemy URL before running unittest discovery.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


BACKEND = Path(__file__).resolve().parents[1] / "backend"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL requis (base PostgreSQL de test)")
class RealtimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx
        from websockets.sync.client import connect

        cls.http = httpx.Client(timeout=5, trust_env=False)
        cls.connect_websocket = staticmethod(connect)
        cls.processes = []
        cls.logs = []
        cls.urls = []
        cls.websocket_urls = []
        cls.addClassCleanup(cls.cleanup)
        for _ in range(2):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            log = tempfile.TemporaryFile(mode="w+")
            cls.logs.append(log)
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=BACKEND,
                env={**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
                stdout=log,
                stderr=log,
            )
            cls.processes.append(process)
            base_url = f"http://127.0.0.1:{port}"
            cls.urls.append(base_url)
            cls.websocket_urls.append(f"ws://127.0.0.1:{port}/ws/todos")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    if cls.http.get(f"{base_url}/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("Le backend de test n'a pas demarre sous 15s")
            if process.poll() is not None:
                log.seek(0)
                raise RuntimeError(log.read())

    @classmethod
    def cleanup(cls):
        for process in cls.processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in cls.logs:
            log.close()
        cls.http.close()

    def test_changes_reach_clients_of_both_replicas(self):
        with self.connect_websocket(self.websocket_urls[0]) as first, self.connect_websocket(self.websocket_urls[1]) as second:
            created = self.http.post(
                f"{self.urls[0]}/todos",
                json={"title": "Test autoscaling", "task_date": "2026-10-29"},
            )
            self.assertEqual(created.status_code, 201, created.text)
            todo_id = created.json()["id"]
            self.addCleanup(self.http.delete, f"{self.urls[0]}/todos/{todo_id}")
            for websocket in (first, second):
                event = json.loads(websocket.recv(timeout=5))
                self.assertEqual(event, {"type": "created", "todo_id": todo_id, "task_date": "2026-10-29"})

            updated = self.http.patch(
                f"{self.urls[1]}/todos/{todo_id}",
                json={"status": "done", "task_date": "2026-10-30"},
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            for websocket in (first, second):
                event = json.loads(websocket.recv(timeout=5))
                self.assertEqual(event["type"], "updated")
                self.assertEqual(event["task_date"], "2026-10-30")
                self.assertEqual(event["previous_task_date"], "2026-10-29")

            deleted = self.http.delete(f"{self.urls[0]}/todos/{todo_id}")
            self.assertEqual(deleted.status_code, 204, deleted.text)
            for websocket in (first, second):
                event = json.loads(websocket.recv(timeout=5))
                self.assertEqual(event, {"type": "deleted", "todo_id": todo_id, "task_date": "2026-10-30"})

    def test_rolled_back_transaction_sends_no_notification(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        sys.path.insert(0, str(BACKEND))
        from app.realtime import notify_todo_change

        engine = create_engine(os.environ["TEST_DATABASE_URL"])
        try:
            with self.connect_websocket(self.websocket_urls[0]) as websocket:
                with Session(engine) as session:
                    notify_todo_change(session, {"type": "created", "todo_id": -1, "task_date": "2026-10-29"})
                    session.rollback()
                with self.assertRaises(TimeoutError):
                    websocket.recv(timeout=0.2)
                # A subsequent committed notification still reaches the client.
                with Session(engine) as session:
                    notify_todo_change(session, {"type": "updated", "todo_id": -1, "task_date": "2026-10-29"})
                    session.commit()
                self.assertEqual(json.loads(websocket.recv(timeout=5))["type"], "updated")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
