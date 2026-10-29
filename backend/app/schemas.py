from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TodoStatus


class TodoBase(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = None
    status: TodoStatus = TodoStatus.todo
    task_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class TodoCreate(TodoBase):
    pass


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    status: TodoStatus | None = None
    task_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("title", "status", "task_date")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Ce champ ne peut pas etre nul")
        return value


class TodoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TodoStatus
    task_date: date
    created_at: datetime
    updated_at: datetime
