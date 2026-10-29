"""Browser smoke test. Requires TEST_BASE_URL, TEST_BROWSER=1 and Playwright."""

import os
import re
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv("TEST_BASE_URL") and os.getenv("TEST_BROWSER"), "TEST_BASE_URL et TEST_BROWSER requis")
class BrowserTests(unittest.TestCase):
    def test_kanban_actions_and_live_updates_in_two_tabs(self):
        from playwright.sync_api import sync_playwright, expect

        base_url = os.environ["TEST_BASE_URL"].rstrip("/")
        title = f"Verification navigateur {uuid4().hex}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(timezone_id="Europe/Paris")
            context.add_init_script("""
                const NativeWebSocket = window.WebSocket;
                window.WebSocket = class extends NativeWebSocket {
                    constructor(...args) {
                        super(...args);
                        window.__verificationSocket = this;
                    }
                };
            """)
            errors = []
            pages = [context.new_page(), context.new_page()]
            for page in pages:
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base_url)
                expect(page.get_by_role("heading", name="Kanban du jour")).to_be_visible()
                page.get_by_label("Jour", exact=True).fill("2099-11-14")
                expect(page.locator(".empty-state")).to_have_count(0)
            first, second = pages
            try:
                first.get_by_role("button", name="Nouveau ticket").click()
                first.get_by_label("Titre de la tache").fill(title)
                first.get_by_label("Description", exact=True).fill("Description du test")
                first.get_by_role("button", name="Creer", exact=True).click()
                cards = [page.locator("article.todo-card").filter(has=page.get_by_role("heading", name=title, exact=True)) for page in pages]
                for card in cards:
                    expect(card).to_have_count(1, timeout=10000)
                cards[0].get_by_role("button", name="Modifier la description", exact=True).click()
                cards[0].get_by_role("textbox", name="Modifier la description", exact=True).fill("Description modifiee")
                cards[0].get_by_role("button", name="Enregistrer", exact=True).click()
                expect(cards[1].get_by_role("button", name="Description modifiee", exact=True)).to_be_visible(timeout=10000)
                tasks = context.request.get(f"{base_url}/api/todos?task_date=2099-11-14").json()
                todo = next(task for task in tasks if task["title"] == title)
                first.evaluate("window.__verificationSocket.close()")
                response = context.request.patch(f"{base_url}/api/todos/{todo['id']}", data={"description": "Modification pendant la reconnexion"})
                self.assertTrue(response.ok)
                expect(cards[0].get_by_role("button", name="Modification pendant la reconnexion", exact=True)).to_be_visible(timeout=10000)
                cards[0].get_by_role("button", name="Terminee", exact=True).click()
                for card in cards:
                    expect(card).to_have_class(re.compile(r"\bdone\b"), timeout=10000)
                cards[0].drag_to(first.locator(".kanban-column").nth(1))
                for card in cards:
                    expect(card).to_have_class(re.compile(r"\bin_progress\b"), timeout=10000)
                first.get_by_role("button", name="Jour suivant", exact=True).click()
                expect(cards[0]).to_have_count(0)
                first.get_by_role("button", name="Jour precedent", exact=True).click()
                expect(cards[0]).to_have_count(1)
                first.set_viewport_size({"width": 390, "height": 844})
                expect(first.get_by_role("button", name="Nouveau ticket")).to_be_visible()
                self.assertLessEqual(first.evaluate("document.documentElement.scrollWidth"), 390)
                cards[0].get_by_role("button", name="Supprimer", exact=True).click()
                for card in cards:
                    expect(card).to_have_count(0, timeout=10000)
                self.assertEqual(errors, [])
            finally:
                tasks = context.request.get(f"{base_url}/api/todos?task_date=2099-11-14").json()
                for task in tasks:
                    if task["title"] == title:
                        context.request.delete(f"{base_url}/api/todos/{task['id']}")
                context.close()
                browser.close()


if __name__ == "__main__":
    unittest.main()
