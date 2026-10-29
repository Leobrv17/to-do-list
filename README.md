# Daily Dashboard V1

MVP conteneurise d'un tableau de bord quotidien avec une to-do list.

## Stack

- Frontend: React + Vite, servi par Nginx
- Backend: Python + FastAPI
- Base de donnees: PostgreSQL avec volume Docker persistant
- Orchestration: Docker Compose
- Autoscaling: conteneur dedie pilotant le nombre d'instances du backend selon la charge CPU

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
+-- autoscaler
|   +-- autoscale.sh
|   +-- Dockerfile.autoscaler
+-- backend
|   +-- app
|   |   +-- __init__.py
|   |   +-- database.py
|   |   +-- main.py
|   |   +-- models.py
|   |   +-- realtime.py
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

## Autoscaling du backend

Le service `autoscaler` demarre automatiquement avec `docker compose up --build`.
Il adapte le script fourni pour Docker Swarm a Docker Compose : aucune initialisation
Swarm ni commande `docker stack deploy` n'est necessaire.

Par defaut, il mesure toutes les 10 secondes le CPU moyen des instances du backend.
Il ajoute une instance au-dessus de 80 % et en retire une sous 10 %, avec un minimum
de 1 et un maximum de 5. Le pourcentage correspond a l'utilisation d'un coeur par
instance, pas au pourcentage de CPU de l'hote. Un delai de 60 secondes au demarrage
et apres chaque changement evite les variations trop rapides. Les bornes MIN/MAX
sont appliquees immediatement. Une mesure absente ou invalide est ignoree.

Ces valeurs se configurent dans `.env` :

```dotenv
AUTOSCALE_MIN_REPLICAS=1
AUTOSCALE_MAX_REPLICAS=5
AUTOSCALE_CPU_SCALE_UP=80
AUTOSCALE_CPU_SCALE_DOWN=10
AUTOSCALE_INTERVAL=10
AUTOSCALE_COOLDOWN=60
```

Apres modification, recreer le conteneur de controle :

```bash
docker compose up -d --no-deps --force-recreate autoscaler
```

Pour consulter son activite et le nombre d'instances :

```bash
docker compose logs -f autoscaler
docker compose ps backend
```

Pour suspendre l'autoscaling et revenir a une seule instance :

```bash
docker compose stop autoscaler
docker compose up -d --no-deps --scale backend=1 backend
```

Pour le reactiver : `docker compose start autoscaler`.

Le backend utilise des noms de conteneurs generes par Compose pour autoriser la
replication. Nginx repartit les requetes API et WebSocket entre les instances et
actualise les adresses via le DNS Docker toutes les secondes. Les notifications
WebSocket passent par `LISTEN/NOTIFY` dans PostgreSQL afin qu'une modification
effectuee sur une instance soit transmise aux clients connectes aux autres.
PostgreSQL, le frontend et l'agent vocal restent chacun a une instance.

L'autoscaler utilise le fichier `docker-compose.yml` du projet monte dans
`/workspace` en lecture seule et detecte le nom du projet avec les labels Docker,
y compris avec `docker compose -p mon-projet up --build`. Utiliser le fichier
principal et reconstruire le backend et le frontend avec `--build` lors de cette
mise a jour. Les fichiers Compose supplementaires passes avec `-f` ne sont pas
repris par l'autoscaler.

Le socket `/var/run/docker.sock` lui permet de creer et supprimer les instances :
il donne donc un acces privilegie au moteur Docker. Le conteneur n'a aucun reseau
ni port expose. Utiliser uniquement cette image et ce script de confiance.

La [mise a l'echelle Compose](https://docs.docker.com/reference/cli/docker/compose/up/),
le [proxy Nginx avec variables](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)
et les [notifications Psycopg](https://www.psycopg.org/psycopg3/docs/advanced/async.html#asynchronous-notifications)
sont documentees par leurs projets respectifs.

## Verification de l'autoscaling

Le resultat de la verification complete du projet est dans [VERIFICATION.md](VERIFICATION.md).

Les tests du script simulent Docker et ne necessitent pas de moteur actif :

```bash
python3 -m unittest discover -s tests -p 'test_autoscaler.py' -v
```

Les tests d'integration dans `tests/test_realtime.py` lancent deux backends et
verifient les notifications entre instances et l'absence d'evenement apres un
rollback. Ils necessitent les dependances de `backend/requirements.txt`, `httpx`
et une variable `TEST_DATABASE_URL` contenant une URL SQLAlchemy
`postgresql+psycopg://...` vers une base PostgreSQL reservee aux tests. Avec cette
configuration, lancer `python3 -m unittest discover -s tests -v` pour tout verifier.

Pour les tests HTTP, WebSocket, commandes vocales et interface Chrome sur la
stack demarree, installer `tests/requirements.txt` dans un environnement virtuel,
puis lancer :

```bash
TEST_BASE_URL=http://127.0.0.1:3000 TEST_BROWSER=1 python3 -m unittest discover -s tests -v
```

Le test navigateur necessite Google Chrome installe. Les tests de l'agent vocal
couvrent le fallback et simulent les reponses OpenAI. Ajouter `TEST_REAL_VOICE=1`
pour verifier aussi `/voice/command` avec la configuration reelle du service :
si une cle OpenAI est configuree, ce test effectue un appel reel. Les tickets
crees par les tests sont supprimes apres execution. Les suites sans les variables
requises sont explicitement ignorees.

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
- L'autoscaler utilise aussi un systeme de fichiers en lecture seule et n'a aucun acces reseau ; son acces au socket Docker reste privilegie
