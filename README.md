# Daily Dashboard V1

MVP conteneurise d'un tableau de bord quotidien avec une to-do list.

## Stack

- Frontend: React + Vite, servi par Nginx
- Backend: Python + FastAPI
- Base de donnees: PostgreSQL avec volume Docker persistant
- Orchestration: Docker Compose

## Fonctionnalites

- Affichage des taches du jour en Kanban: `A faire`, `En cours`, `Terminee`
- Ajout d'une tache via une modale avec titre, description et statut
- Changement rapide du statut d'une tache
- Drag and drop des cartes entre les colonnes pour changer le statut
- Edition inline de la description
- Suppression d'une tache
- Mise a jour automatique de l'affichage via WebSocket
- Navigation rapide entre les jours avec boutons precedent/suivant
- Commandes vocales depuis le dashboard via un service Docker dedie `voice-agent`
- Interpretation souple par IA quand `OPENAI_API_KEY` est configuree

Exemples de commandes vocales:

- "Ajoute un ticket appeler le dentiste"
- "Cree une tache finir le rapport description avant 18h"
- "Mets finir le rapport en cours"
- "Marque appeler le dentiste termine"
- "Supprime appeler le dentiste"

## Arborescence

```text
.
+-- backend
|   +-- app
|   |   +-- __init__.py
|   |   +-- database.py
|   |   +-- main.py
|   |   +-- models.py
|   |   +-- schemas.py
|   +-- Dockerfile
|   +-- requirements.txt
+-- frontend
|   +-- src
|   |   +-- api.js
|   |   +-- App.jsx
|   |   +-- main.jsx
|   |   +-- styles.css
|   +-- Dockerfile
|   +-- index.html
|   +-- nginx.conf
|   +-- package.json
+-- docker-compose.yml
+-- README.md
```

## Lancement

```bash
docker compose up --build
```

L'application est ensuite disponible sur:

- Frontend: http://localhost:3000
- API via le frontend: http://localhost:3000/api
- Agent vocal via le frontend: http://localhost:3000/voice

Par defaut, le backend et PostgreSQL ne sont pas exposes sur l'hote. Ils communiquent uniquement sur des reseaux Docker internes.

## Configuration

Les valeurs PostgreSQL peuvent etre personnalisees avec un fichier `.env` cree depuis `.env.example`:

```bash
cp .env.example .env
```

Pour activer le vrai agent IA, renseigner aussi:

```bash
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_MODEL=gpt-5-mini
```

Sans cle API, le service vocal reste disponible mais repasse en mode fallback a regles simples.

## Endpoints principaux

- `GET /api/todos?task_date=YYYY-MM-DD`
- `POST /api/todos`
- `PATCH /api/todos/{todo_id}`
- `DELETE /api/todos/{todo_id}`
- WebSocket: `ws://localhost:3000/ws/todos`
- `POST /voice/command`

Les statuts acceptes sont `todo`, `in_progress` et `done`.

## Securite Docker Compose

- Seul le frontend expose un port sur l'hote: `127.0.0.1:3000`
- Le backend est accessible uniquement par le frontend via le reseau interne `app_internal`
- Le service vocal est accessible par le frontend via `app_internal` et utilise le reseau `public` uniquement pour ses appels sortants vers OpenAI
- PostgreSQL est accessible uniquement par le backend via le reseau interne `data_internal`
- `no-new-privileges` est active sur les services
- Le frontend et le backend utilisent un systeme de fichiers en lecture seule avec `tmpfs` pour les chemins temporaires
