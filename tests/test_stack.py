"""HTTP/WebSocket smoke tests against a running stack (TEST_BASE_URL).

Only tasks created by this suite are modified or removed.
"""

import json
import os
import re
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv("TEST_BASE_URL"), "TEST_BASE_URL requis (stack demarree)")
class StackTests(unittest.TestCase):
    def setUp(self):
        import httpx

        self.base_url = os.environ["TEST_BASE_URL"].rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=10, trust_env=False)
        self.ids = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for todo_id in self.ids:
            self.client.delete(f"/api/todos/{todo_id}")
        self.client.close()

    def create(self, **values):
        response = self.client.post("/api/todos", json={
            "title": f"Verification {uuid4().hex}",
            "task_date": "2099-11-14",
            **values,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.ids.append(response.json()["id"])
        return response.json()

    def test_frontend_assets_and_service_health(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.text)
        self.assertGreaterEqual(len(assets), 2)
        for asset in assets:
            self.assertEqual(self.client.get(asset).status_code, 200, asset)
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        self.assertEqual(self.client.get("/voice/health").json()["status"], "ok")

    def test_crud_statuses_descriptions_and_date_filter(self):
        todo = self.create(description="Description initiale")
        for status in ("in_progress", "done", "todo"):
            response = self.client.patch(f"/api/todos/{todo['id']}", json={"status": status})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], status)
        response = self.client.patch(f"/api/todos/{todo['id']}", json={"description": None, "task_date": "2099-11-15"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["description"])
        for task_date, present in (("2099-11-14", False), ("2099-11-15", True)):
            tasks = self.client.get("/api/todos", params={"task_date": task_date}).json()
            self.assertEqual(any(task["id"] == todo["id"] for task in tasks), present)
        self.assertEqual(self.client.delete(f"/api/todos/{todo['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/todos/{todo['id']}").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/todos/{todo['id']}", json={"status": "done"}).status_code, 404)

    def test_proxy_delivers_events_to_multiple_websocket_clients(self):
        from websockets.sync.client import connect

        websocket_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/todos"
        with connect(websocket_url) as first, connect(websocket_url) as second:
            todo = self.create()
            for websocket in (first, second):
                event = json.loads(websocket.recv(timeout=10))
                self.assertEqual(event["type"], "created")
                self.assertEqual(event["todo_id"], todo["id"])

    def test_invalid_creation_and_filters_return_validation_errors(self):
        for payload in (
            {"title": ""}, {"title": " "}, {"title": "x" * 161},
            {"title": "Valide", "status": "invalid"},
            {"title": "Valide", "task_date": "invalid"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/todos", json=payload)
                if response.status_code == 201:
                    self.ids.append(response.json()["id"])
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/todos?task_date=invalide").status_code, 422)

    def test_invalid_update_keeps_task_intact(self):
        todo = self.create()
        for payload in ({"title": None}, {"title": " "}, {"status": None}, {"task_date": None}, {"status": "invalid"}):
            with self.subTest(payload=payload):
                response = self.client.patch(f"/api/todos/{todo['id']}", json=payload)
                self.assertEqual(response.status_code, 422, response.text)

    @unittest.skipUnless(os.getenv("TEST_REAL_VOICE"), "TEST_REAL_VOICE requis (utilise la configuration vocale reelle)")
    def test_configured_voice_http_endpoint_creates_task(self):
        title = f"Verification vocale {uuid4().hex}"
        task_date = "2099-11-18"
        response = self.client.post("/voice/command", json={
            "transcript": f"Ajoute un ticket avec exactement ce titre : {title}",
            "task_date": task_date,
        }, timeout=30)
        tasks = self.client.get("/api/todos", params={"task_date": task_date}).json()
        matching = [task for task in tasks if title.lower() in task["title"].lower()]
        self.ids.extend(task["id"] for task in matching)
        self.assertEqual(response.status_code, 200, "La commande vocale configuree a echoue")
        self.assertEqual(response.json()["action"], "created")
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
