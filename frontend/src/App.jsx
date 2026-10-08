import React, { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Edit3,
  Loader2,
  Mic,
  MicOff,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";

import {
  createTodo,
  deleteTodo,
  listTodos,
  runVoiceCommand,
  updateTodo,
} from "./api";
import "./styles.css";

const statuses = [
  { value: "todo", label: "A faire", icon: Circle },
  { value: "in_progress", label: "En cours", icon: Clock3 },
  { value: "done", label: "Terminee", icon: Check },
];

function todayIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftDate(dateValue, offset) {
  const [year, month, day] = dateValue.split("-").map(Number);
  const nextDate = new Date(year, month - 1, day);
  nextDate.setDate(nextDate.getDate() + offset);

  const nextYear = nextDate.getFullYear();
  const nextMonth = String(nextDate.getMonth() + 1).padStart(2, "0");
  const nextDay = String(nextDate.getDate()).padStart(2, "0");
  return `${nextYear}-${nextMonth}-${nextDay}`;
}

function websocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/todos`;
}

function speechRecognitionApi() {
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

function App() {
  const [taskDate, setTaskDate] = useState(todayIso());
  const [todos, setTodos] = useState([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("todo");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [draggedTodoId, setDraggedTodoId] = useState(null);
  const [dragOverStatus, setDragOverStatus] = useState(null);
  const [isListening, setIsListening] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("");
  const [error, setError] = useState("");

  const doneCount = useMemo(
    () => todos.filter((todo) => todo.status === "done").length,
    [todos],
  );

  const todosByStatus = useMemo(
    () =>
      statuses.reduce((groups, item) => {
        groups[item.value] = todos.filter((todo) => todo.status === item.value);
        return groups;
      }, {}),
    [todos],
  );

  async function loadTodos(date = taskDate, options = {}) {
    const { showLoading = true } = options;
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      setTodos(await listTodos(date));
    } catch (err) {
      setError("Impossible de charger les taches.");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    loadTodos(taskDate);
  }, [taskDate]);

  useEffect(() => {
    let reconnectTimer;
    let shouldReconnect = true;
    let socket;

    function connect() {
      socket = new WebSocket(websocketUrl());

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          const touchesCurrentDate =
            message.task_date === taskDate || message.previous_task_date === taskDate;

          if (touchesCurrentDate) {
            loadTodos(taskDate, { showLoading: false });
          }
        } catch (err) {
          setError("Message temps reel invalide.");
        }
      };

      socket.onclose = () => {
        if (shouldReconnect) {
          reconnectTimer = window.setTimeout(connect, 1500);
        }
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();

    return () => {
      shouldReconnect = false;
      window.clearTimeout(reconnectTimer);
      if (socket) {
        socket.close();
      }
    };
  }, [taskDate]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!title.trim()) return;

    setSaving(true);
    setError("");
    try {
      const todo = await createTodo({
        title,
        description: description || null,
        status,
        task_date: taskDate,
      });
      setTodos((current) => [...current, todo]);
      setTitle("");
      setDescription("");
      setStatus("todo");
      setIsCreateOpen(false);
    } catch (err) {
      setError("Impossible d'ajouter la tache.");
    } finally {
      setSaving(false);
    }
  }

  function closeCreateModal() {
    setIsCreateOpen(false);
    setTitle("");
    setDescription("");
    setStatus("todo");
  }

  async function changeStatus(todo, nextStatus) {
    if (todo.status === nextStatus) return;

    const previousTodos = todos;
    setTodos((current) =>
      current.map((item) =>
        item.id === todo.id ? { ...item, status: nextStatus } : item,
      ),
    );
    try {
      await updateTodo(todo.id, { status: nextStatus });
    } catch (err) {
      setTodos(previousTodos);
      setError("Le statut n'a pas pu etre mis a jour.");
    }
  }

  function handleDragStart(event, todo) {
    setDraggedTodoId(todo.id);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(todo.id));
  }

  function handleDragEnd() {
    setDraggedTodoId(null);
    setDragOverStatus(null);
  }

  function handleDragOver(event, statusValue) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDragOverStatus(statusValue);
  }

  function handleDragLeave(event, statusValue) {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      setDragOverStatus((current) => (current === statusValue ? null : current));
    }
  }

  async function handleDrop(event, nextStatus) {
    event.preventDefault();
    const todoId = Number(event.dataTransfer.getData("text/plain") || draggedTodoId);
    const todo = todos.find((item) => item.id === todoId);

    setDraggedTodoId(null);
    setDragOverStatus(null);

    if (todo) {
      await changeStatus(todo, nextStatus);
    }
  }

  function startEditingDescription(todo) {
    setEditingId(todo.id);
    setDescriptionDraft(todo.description || "");
  }

  function cancelEditingDescription() {
    setEditingId(null);
    setDescriptionDraft("");
  }

  async function saveDescription(todo) {
    const previousTodos = todos;
    const nextDescription = descriptionDraft.trim() || null;

    setTodos((current) =>
      current.map((item) =>
        item.id === todo.id ? { ...item, description: nextDescription } : item,
      ),
    );
    setEditingId(null);
    setDescriptionDraft("");

    try {
      await updateTodo(todo.id, { description: nextDescription });
    } catch (err) {
      setTodos(previousTodos);
      setError("La description n'a pas pu etre mise a jour.");
    }
  }

  async function removeTodo(todo) {
    const previousTodos = todos;
    setTodos((current) => current.filter((item) => item.id !== todo.id));
    try {
      await deleteTodo(todo.id);
    } catch (err) {
      setTodos(previousTodos);
      setError("La suppression a echoue.");
    }
  }

  function startVoiceCommand() {
    const Recognition = speechRecognitionApi();
    if (!Recognition) {
      setVoiceMessage("Reconnaissance vocale indisponible dans ce navigateur.");
      return;
    }

    const recognition = new Recognition();
    recognition.lang = "fr-FR";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setIsListening(true);
      setVoiceMessage("J'ecoute...");
    };

    recognition.onerror = () => {
      setIsListening(false);
      setVoiceMessage("Je n'ai pas pu comprendre la commande.");
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.onresult = async (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript || "";
      if (!transcript.trim()) {
        setVoiceMessage("Commande vide.");
        return;
      }

      setVoiceMessage(`Commande: ${transcript}`);
      try {
        const result = await runVoiceCommand({
          transcript,
          task_date: taskDate,
        });
        setVoiceMessage(`${result.mode === "ai" ? "IA" : "Fallback"}: ${result.message}`);
        loadTodos(taskDate, { showLoading: false });
      } catch (err) {
        setVoiceMessage("La commande vocale n'a pas pu etre executee.");
      }
    };

    recognition.start();
  }

  return (
    <main className="app-shell">
      <section className="toolbar">
        <div>
          <p className="eyebrow">Daily Dashboard</p>
          <h1>Kanban du jour</h1>
        </div>
        <div className="toolbar-actions">
          <div className="date-block">
            <label htmlFor="task-date">Jour</label>
            <div className="date-controls">
              <button
                type="button"
                title="Jour precedent"
                aria-label="Jour precedent"
                onClick={() => setTaskDate((current) => shiftDate(current, -1))}
              >
                <ChevronLeft size={18} />
              </button>
              <input
                id="task-date"
                type="date"
                value={taskDate}
                onChange={(event) => setTaskDate(event.target.value)}
              />
              <button
                type="button"
                title="Jour suivant"
                aria-label="Jour suivant"
                onClick={() => setTaskDate((current) => shiftDate(current, 1))}
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
          <button
            type="button"
            className="primary-action"
            onClick={() => setIsCreateOpen(true)}
          >
            <Plus size={18} />
            Nouveau ticket
          </button>
          <button
            type="button"
            className={`voice-action ${isListening ? "listening" : ""}`}
            title="Commande vocale"
            aria-label="Commande vocale"
            onClick={startVoiceCommand}
            disabled={isListening}
          >
            {isListening ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
        </div>
      </section>

      <section className="summary">
        <span>{todos.length} tache(s)</span>
        <span>{doneCount} terminee(s)</span>
        {voiceMessage ? <span className="voice-status">{voiceMessage}</span> : null}
      </section>

      {error ? <p className="error">{error}</p> : null}

      {isCreateOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeCreateModal}>
          <section
            className="modal-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-ticket-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <h2 id="create-ticket-title">Nouveau ticket</h2>
              <button
                type="button"
                title="Fermer"
                aria-label="Fermer"
                onClick={closeCreateModal}
              >
                <X size={18} />
              </button>
            </header>
            <form className="todo-form modal-form" onSubmit={handleSubmit}>
              <input
                autoFocus
                aria-label="Titre de la tache"
                placeholder="Titre du ticket"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
              <textarea
                aria-label="Description"
                placeholder="Description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
              <div className="form-row">
                <select
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                >
                  {statuses.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <button type="submit" disabled={saving || !title.trim()}>
                  {saving ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
                  Creer
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}

      <section className="kanban-board" aria-live="polite">
        {loading ? (
          <div className="empty-state">
            <Loader2 className="spin" />
          </div>
        ) : (
          statuses.map((column) => {
            const ColumnIcon = column.icon;
            const columnTodos = todosByStatus[column.value] || [];

            return (
              <section
                className={`kanban-column ${
                  dragOverStatus === column.value ? "drop-target" : ""
                }`}
                key={column.value}
                onDragOver={(event) => handleDragOver(event, column.value)}
                onDragLeave={(event) => handleDragLeave(event, column.value)}
                onDrop={(event) => handleDrop(event, column.value)}
              >
                <header className="column-header">
                  <span>
                    <ColumnIcon size={18} />
                    {column.label}
                  </span>
                  <strong>{columnTodos.length}</strong>
                </header>

                <div className="column-stack">
                  {columnTodos.length === 0 ? (
                    <p className="column-empty">Aucune tache</p>
                  ) : (
                    columnTodos.map((todo) => (
                      <article
                        className={`todo-card ${todo.status} ${
                          draggedTodoId === todo.id ? "dragging" : ""
                        }`}
                        draggable={editingId !== todo.id}
                        key={todo.id}
                        onDragStart={(event) => handleDragStart(event, todo)}
                        onDragEnd={handleDragEnd}
                      >
                        <div className="todo-content">
                          <h2>{todo.title}</h2>
                          {editingId === todo.id ? (
                            <div className="description-editor">
                              <textarea
                                aria-label="Modifier la description"
                                value={descriptionDraft}
                                onChange={(event) =>
                                  setDescriptionDraft(event.target.value)
                                }
                              />
                              <div className="editor-actions">
                                <button
                                  type="button"
                                  title="Enregistrer"
                                  aria-label="Enregistrer"
                                  onClick={() => saveDescription(todo)}
                                >
                                  <Save size={17} />
                                </button>
                                <button
                                  type="button"
                                  title="Annuler"
                                  aria-label="Annuler"
                                  onClick={cancelEditingDescription}
                                >
                                  <X size={17} />
                                </button>
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="description-button"
                              onClick={() => startEditingDescription(todo)}
                            >
                              {todo.description || "Ajouter une description"}
                            </button>
                          )}
                        </div>
                        <div className="todo-actions">
                          <div className="status-group" aria-label="Statut">
                            {statuses.map((item) => {
                              const Icon = item.icon;
                              return (
                                <button
                                  key={item.value}
                                  type="button"
                                  className={todo.status === item.value ? "active" : ""}
                                  title={item.label}
                                  aria-label={item.label}
                                  onClick={() => changeStatus(todo, item.value)}
                                >
                                  <Icon size={17} />
                                </button>
                              );
                            })}
                          </div>
                          <button
                            type="button"
                            title="Modifier la description"
                            aria-label="Modifier la description"
                            onClick={() => startEditingDescription(todo)}
                          >
                            <Edit3 size={18} />
                          </button>
                          <button
                            type="button"
                            className="danger"
                            title="Supprimer"
                            aria-label="Supprimer"
                            onClick={() => removeTodo(todo)}
                          >
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </section>
            );
          })
        )}
      </section>
    </main>
  );
}

export default App;
