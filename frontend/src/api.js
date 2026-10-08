const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";
const VOICE_BASE_URL = import.meta.env.VITE_VOICE_URL || "/voice";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "API request failed");
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function listTodos(taskDate) {
  return request(`/todos?task_date=${taskDate}`);
}

export function createTodo(payload) {
  return request("/todos", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateTodo(id, payload) {
  return request(`/todos/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteTodo(id) {
  return request(`/todos/${id}`, {
    method: "DELETE",
  });
}

export async function runVoiceCommand(payload) {
  const response = await fetch(`${VOICE_BASE_URL}/command`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Voice command failed");
  }

  return response.json();
}
