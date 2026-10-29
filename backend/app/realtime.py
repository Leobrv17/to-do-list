import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

import psycopg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine


logger = logging.getLogger(__name__)
CHANNEL = "todo_events"


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, str | int]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except (OSError, RuntimeError, WebSocketDisconnect):
                self.disconnect(connection)


manager = ConnectionManager()


def notify_todo_change(db: Session, message: dict[str, str | int]) -> None:
    # PostgreSQL delivers the notification to every replica only after commit.
    db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": json.dumps(message)},
    )


async def listen_for_changes(ready: asyncio.Event) -> None:
    database_url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(
                database_url, autocommit=True, connect_timeout=5
            ) as connection:
                await connection.execute(f"LISTEN {CHANNEL}")
                ready.set()
                async for notification in connection.notifies():
                    await manager.broadcast(json.loads(notification.payload))
        except (psycopg.Error, OSError):
            logger.exception("Connexion aux notifications PostgreSQL perdue, nouvelle tentative dans 2s")
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ready = asyncio.Event()
    listener = asyncio.create_task(listen_for_changes(ready))
    try:
        # Start accepting requests after LISTEN, so the first event is received.
        await ready.wait()
        yield
    finally:
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener
