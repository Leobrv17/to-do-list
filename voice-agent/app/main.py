import os
import json
import re
import unicodedata
from datetime import date

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

app = FastAPI(title="Daily Dashboard Voice Agent", version="0.1.0")


class VoiceCommand(BaseModel):
    transcript: str = Field(min_length=1)
    task_date: date


class VoiceCommandResult(BaseModel):
    action: str
    message: str
    transcript: str
    mode: str = "fallback_rules"


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", ascii_value.lower()).strip()


def clean_title(value: str) -> str:
    value = re.sub(r"\b(description|avec description|statut|en cours|termine|terminee|a faire)\b.*", "", value, flags=re.I)
    value = re.sub(r"^[\s:,-]+|[\s:,-]+$", "", value)
    return value.strip().capitalize()


def wanted_status(normalized: str) -> str | None:
    if any(token in normalized for token in ("en cours", "commence", "demarre", "progress")):
        return "in_progress"
    if any(token in normalized for token in ("termine", "terminee", "fini", "faite", "done")):
        return "done"
    if any(token in normalized for token in ("a faire", "todo", "non termine", "non terminee")):
        return "todo"
    return None


def extract_description(transcript: str) -> str | None:
    match = re.search(r"(?:description|avec description)\s+(.+)$", transcript, flags=re.I)
    if not match:
        return None
    return match.group(1).strip()


def extract_create_title(transcript: str) -> str:
    title = re.sub(
        r"^(ajoute|ajouter|cree|creer|crée|créer|nouveau|nouvelle)\s+",
        "",
        transcript,
        flags=re.I,
    )
    title = re.sub(r"^(un|une|le|la)?\s*(ticket|tache|tâche)\s*", "", title, flags=re.I)
    return clean_title(title)


def match_todo(transcript: str, todos: list[dict]) -> dict | None:
    normalized = normalize(transcript)
    best_match = None
    best_score = 0

    for todo in todos:
        title = normalize(todo["title"])
        words = [word for word in title.split() if len(word) > 2]
        score = sum(1 for word in words if word in normalized)
        if title and title in normalized:
            score += 3
        if score > best_score:
            best_match = todo
            best_score = score

    return best_match if best_score > 0 else None


async def backend_request(method: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=8) as client:
        response = await client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text)
    return response


async def get_todos(task_date: date) -> list[dict]:
    response = await backend_request("GET", "/todos", params={"task_date": task_date.isoformat()})
    return response.json()


def response_text(response_payload: dict) -> str:
    if response_payload.get("output_text"):
        return response_payload["output_text"]

    for item in response_payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")

    return ""


def action_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "delete", "clarify", "none"],
            },
            "todo_id": {"type": ["integer", "null"]},
            "title": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]},
            "status": {
                "type": ["string", "null"],
                "enum": ["todo", "in_progress", "done", None],
            },
            "task_date": {"type": ["string", "null"]},
            "message": {"type": "string"},
        },
        "required": [
            "action",
            "todo_id",
            "title",
            "description",
            "status",
            "task_date",
            "message",
        ],
    }


async def ask_ai_for_action(command: VoiceCommand, todos: list[dict]) -> dict | None:
    if not OPENAI_API_KEY:
        return None

    today = date.today().isoformat()
    system_prompt = (
        "Tu es un agent IA de gestion de Kanban personnel. "
        "Tu comprends des commandes vocales en francais, meme imparfaites, et tu choisis une seule action. "
        "Tu peux creer, modifier, supprimer, demander une clarification ou ne rien faire. "
        "Pour modifier ou supprimer, choisis un todo_id parmi les tickets fournis. "
        "Pour creer, extrais un titre court et une description si elle est utile. "
        "Les statuts autorises sont: todo, in_progress, done. "
        "Si l'utilisateur dit aujourd'hui, demain ou hier, calcule la date ISO a partir de la date locale fournie. "
        "Ne modifie jamais plusieurs tickets en une seule reponse. "
        "Si tu n'es pas assez sur du ticket cible, utilise clarify."
    )
    user_context = {
        "transcript": command.transcript,
        "selected_task_date": command.task_date.isoformat(),
        "local_today": today,
        "available_todos_for_selected_date": todos,
    }
    payload = {
        "model": OPENAI_MODEL,
        "store": False,
        "input": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_context, ensure_ascii=False),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "todo_voice_action",
                "strict": True,
                "schema": action_schema(),
            }
        },
    }

    async with httpx.AsyncClient(base_url=OPENAI_BASE_URL, timeout=20) as client:
        response = await client.post(
            "/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text)

    text = response_text(response.json())
    if not text:
        raise HTTPException(status_code=502, detail="OpenAI response did not include text output")

    return json.loads(text)


async def execute_ai_action(decision: dict, command: VoiceCommand, todos: list[dict]) -> VoiceCommandResult:
    transcript = command.transcript.strip()
    action = decision["action"]
    target_date = decision.get("task_date") or command.task_date.isoformat()

    if action == "create":
        title = (decision.get("title") or "").strip()
        if not title:
            return VoiceCommandResult(
                action="clarify",
                message="Je peux creer le ticket, mais il me manque son titre.",
                transcript=transcript,
                mode="ai",
            )

        payload = {
            "title": title,
            "description": decision.get("description"),
            "status": decision.get("status") or "todo",
            "task_date": target_date,
        }
        response = await backend_request("POST", "/todos", json=payload)
        todo = response.json()
        return VoiceCommandResult(
            action="created",
            message=decision.get("message") or f"Ticket cree: {todo['title']}",
            transcript=transcript,
            mode="ai",
        )

    todo_id = decision.get("todo_id")
    if action in {"update", "delete"} and todo_id is None:
        matched = match_todo(transcript, todos)
        todo_id = matched["id"] if matched else None

    if action == "update":
        if todo_id is None:
            return VoiceCommandResult(
                action="clarify",
                message=decision.get("message") or "Quel ticket veux-tu modifier ?",
                transcript=transcript,
                mode="ai",
            )

        payload = {}
        if decision.get("title"):
            payload["title"] = decision["title"]
        if decision.get("description") is not None:
            payload["description"] = decision["description"]
        if decision.get("status"):
            payload["status"] = decision["status"]
        if decision.get("task_date"):
            payload["task_date"] = decision["task_date"]

        if not payload:
            return VoiceCommandResult(
                action="clarify",
                message=decision.get("message") or "Que veux-tu changer sur ce ticket ?",
                transcript=transcript,
                mode="ai",
            )

        response = await backend_request("PATCH", f"/todos/{todo_id}", json=payload)
        todo = response.json()
        return VoiceCommandResult(
            action="updated",
            message=decision.get("message") or f"Ticket mis a jour: {todo['title']}",
            transcript=transcript,
            mode="ai",
        )

    if action == "delete":
        if todo_id is None:
            return VoiceCommandResult(
                action="clarify",
                message=decision.get("message") or "Quel ticket veux-tu supprimer ?",
                transcript=transcript,
                mode="ai",
            )

        await backend_request("DELETE", f"/todos/{todo_id}")
        return VoiceCommandResult(
            action="deleted",
            message=decision.get("message") or "Ticket supprime.",
            transcript=transcript,
            mode="ai",
        )

    return VoiceCommandResult(
        action=action,
        message=decision.get("message") or "Je n'ai pas assez d'information pour agir.",
        transcript=transcript,
        mode="ai",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": "ai" if OPENAI_API_KEY else "fallback_rules",
        "model": OPENAI_MODEL if OPENAI_API_KEY else "none",
    }


@app.post("/command", response_model=VoiceCommandResult)
async def run_command(command: VoiceCommand) -> VoiceCommandResult:
    transcript = command.transcript.strip()
    normalized = normalize(transcript)
    todos = await get_todos(command.task_date)

    decision = await ask_ai_for_action(command, todos)
    if decision is not None:
        return await execute_ai_action(decision, command, todos)

    if any(token in normalized for token in ("ajoute", "ajouter", "cree", "creer", "nouveau", "nouvelle")):
        title = extract_create_title(transcript)
        if not title:
            raise HTTPException(status_code=422, detail="Titre de tache introuvable")

        payload = {
            "title": title,
            "description": extract_description(transcript),
            "status": wanted_status(normalized) or "todo",
            "task_date": command.task_date.isoformat(),
        }
        response = await backend_request("POST", "/todos", json=payload)
        todo = response.json()
        return VoiceCommandResult(
            action="created",
            message=f"Ticket cree: {todo['title']}",
            transcript=transcript,
        )

    todo = match_todo(transcript, todos)
    if todo is None:
        return VoiceCommandResult(
            action="not_found",
            message="Je n'ai pas trouve de ticket correspondant pour cette date.",
            transcript=transcript,
        )

    if any(token in normalized for token in ("supprime", "supprimer", "efface", "retire")):
        await backend_request("DELETE", f"/todos/{todo['id']}")
        return VoiceCommandResult(
            action="deleted",
            message=f"Ticket supprime: {todo['title']}",
            transcript=transcript,
        )

    next_status = wanted_status(normalized)
    if next_status is not None:
        response = await backend_request("PATCH", f"/todos/{todo['id']}", json={"status": next_status})
        updated = response.json()
        return VoiceCommandResult(
            action="updated",
            message=f"Statut mis a jour: {updated['title']}",
            transcript=transcript,
        )

    description = extract_description(transcript)
    if description:
        response = await backend_request("PATCH", f"/todos/{todo['id']}", json={"description": description})
        updated = response.json()
        return VoiceCommandResult(
            action="updated",
            message=f"Description mise a jour: {updated['title']}",
            transcript=transcript,
        )

    return VoiceCommandResult(
        action="ignored",
        message="Commande comprise, mais aucune action claire n'a ete detectee.",
        transcript=transcript,
    )
