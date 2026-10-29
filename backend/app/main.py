from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Todo
from app.realtime import lifespan, manager, notify_todo_change
from app.schemas import TodoCreate, TodoRead, TodoUpdate

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Daily Dashboard API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/todos")
async def todos_websocket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/todos", response_model=list[TodoRead])
def list_todos(
    task_date: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
) -> list[Todo]:
    statement = select(Todo).where(Todo.task_date == task_date).order_by(Todo.created_at.asc())
    return list(db.scalars(statement).all())


@app.post("/todos", response_model=TodoRead, status_code=status.HTTP_201_CREATED)
async def create_todo(payload: TodoCreate, db: Session = Depends(get_db)) -> Todo:
    todo = Todo(
        title=payload.title.strip(),
        description=payload.description,
        status=payload.status,
        task_date=payload.task_date or date.today(),
    )
    db.add(todo)
    db.flush()
    notify_todo_change(
        db,
        {
            "type": "created",
            "todo_id": todo.id,
            "task_date": todo.task_date.isoformat(),
        }
    )
    db.commit()
    db.refresh(todo)
    return todo


@app.patch("/todos/{todo_id}", response_model=TodoRead)
async def update_todo(todo_id: int, payload: TodoUpdate, db: Session = Depends(get_db)) -> Todo:
    todo = db.get(Todo, todo_id)
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

    previous_task_date = todo.task_date
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()

    for key, value in changes.items():
        setattr(todo, key, value)

    notify_todo_change(
        db,
        {
            "type": "updated",
            "todo_id": todo.id,
            "task_date": todo.task_date.isoformat(),
            "previous_task_date": previous_task_date.isoformat(),
        }
    )
    db.commit()
    db.refresh(todo)
    return todo


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(todo_id: int, db: Session = Depends(get_db)) -> None:
    todo = db.get(Todo, todo_id)
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

    task_date = todo.task_date
    db.delete(todo)
    notify_todo_change(
        db,
        {
            "type": "deleted",
            "todo_id": todo_id,
            "task_date": task_date.isoformat(),
        }
    )
    db.commit()
