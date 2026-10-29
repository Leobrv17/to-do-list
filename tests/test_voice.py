"""Voice-agent integration tests; OpenAI responses use a local HTTP mock."""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4


@unittest.skipUnless(os.getenv("TEST_BASE_URL"), "TEST_BASE_URL requis (stack demarree)")
class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx

        source = Path(__file__).resolve().parents[1] / "voice-agent" / "app" / "main.py"
        spec = importlib.util.spec_from_file_location("voice_verification", source)
        self.voice = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.voice)
        self.voice.OPENAI_API_KEY = ""
        self.voice.BACKEND_URL = os.environ["TEST_BASE_URL"].rstrip("/") + "/api"
        self.client = httpx.AsyncClient(base_url=self.voice.BACKEND_URL, timeout=10, trust_env=False)
        self.prefix = "Verificationvocale" + uuid4().hex
        self.task_date = "2099-11-16"
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        response = await self.client.get("/todos", params={"task_date": self.task_date})
        for todo in response.json():
            if todo["title"].lower().startswith(self.prefix.lower()):
                await self.client.delete(f"/todos/{todo['id']}")
        await self.client.aclose()

    async def command(self, transcript):
        return await self.voice.run_command(self.voice.VoiceCommand(transcript=transcript, task_date=self.task_date))

    async def test_fallback_creates_updates_and_deletes_task(self):
        self.assertEqual((await self.command(f"Ajoute un ticket {self.prefix}")).action, "created")
        self.assertEqual((await self.command(f"Mets {self.prefix} en cours")).action, "updated")
        tasks = (await self.client.get("/todos", params={"task_date": self.task_date})).json()
        task = next(task for task in tasks if task["title"].lower() == self.prefix.lower())
        self.assertEqual(task["status"], "in_progress")
        self.assertEqual((await self.command(f"Supprime {self.prefix}")).action, "deleted")

    async def test_fallback_reports_unmatched_command(self):
        self.assertEqual((await self.command(f"Termine {self.prefix}")).action, "not_found")

    async def test_fallback_rejects_empty_title(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            await self.command("Ajoute un ticket")
        self.assertEqual(caught.exception.status_code, 422)

    async def test_ai_request_and_actions_with_mocked_openai(self):
        import httpx

        decision = {"action": "create", "todo_id": None, "title": self.prefix, "description": None,
                    "status": "todo", "task_date": self.task_date, "message": "Verification"}
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            self.assertEqual(request.url.path, "/v1/responses")
            return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": json.dumps(decision)}]}]})

        original_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            if kwargs.get("base_url") == self.voice.OPENAI_BASE_URL:
                kwargs["transport"] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)

        self.voice.OPENAI_API_KEY = "verification-local-only"
        with patch.object(self.voice.httpx, "AsyncClient", side_effect=client_factory):
            created = await self.command(f"Cree {self.prefix}")
            self.assertEqual((created.action, created.mode), ("created", "ai"))
            tasks = (await self.client.get("/todos", params={"task_date": self.task_date})).json()
            task = next(task for task in tasks if task["title"] == self.prefix)
            decision.update(action="update", todo_id=task["id"], status="done")
            self.assertEqual((await self.command(f"Termine {self.prefix}")).action, "updated")
            updated = (await self.client.get("/todos", params={"task_date": self.task_date})).json()
            self.assertEqual(next(item for item in updated if item["id"] == task["id"])["status"], "done")
            decision.update(action="delete")
            self.assertEqual((await self.command(f"Supprime {self.prefix}")).action, "deleted")
        self.assertEqual(len(captured), 3)
        self.assertTrue(captured[0]["text"]["format"]["strict"])
        self.assertFalse(captured[0]["store"])

    async def test_ai_requests_clarification_for_missing_title(self):
        command = self.voice.VoiceCommand(transcript="Cree une tache", task_date=self.task_date)
        result = await self.voice.execute_ai_action({"action": "create", "title": None}, command, [])
        self.assertEqual(result.action, "clarify")


if __name__ == "__main__":
    unittest.main()
