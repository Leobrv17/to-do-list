**Vérification de V1 — 29 octobre 2026**

Les images Docker du backend, du frontend, de l'agent vocal et de l'autoscaler
ont été construites. Les cinq services ont été démarrés avec Docker Compose.
L'application reste accessible sur http://localhost:3000.

La dernière exécution découvre 24 tests : **23 réussissent et 1 est ignoré**.
Le test ignoré concerne l'appel vocal réel ; il a été exécuté séparément et
échoue en raison de la clé OpenAI expirée, comme détaillé ci-dessous.

| Contrôle | Résultat |
| --- | --- |
| Script d'autoscaling : seuils, moyenne CPU, bornes, temporisation, erreurs Docker et mesures invalides | 10 tests réussis |
| Notifications entre deux processus backend et absence d'événement après rollback, avec PostgreSQL 17 isolé | 2 tests réussis |
| API via Nginx : CRUD, statuts, descriptions, dates, validation, WebSockets et ressources frontend | 5 tests réussis |
| Chrome : création, édition, statuts, glisser-déposer, dates, mobile, synchronisation de deux onglets et reconnexion WebSocket | 1 test réussi |
| Agent vocal : fallback, actions IA avec réponses OpenAI simulées et clarification | 5 tests réussis |
| Endpoint vocal réel `/voice/command` avec la configuration de V1 | Échec : clé OpenAI expirée (`expired_secret_key`), HTTP 502 |
| Configuration Compose et syntaxe du script shell | Valides |
| Configuration Nginx dans son conteneur | Valide |
| Dépendances Python dans les conteneurs backend et vocal (`pip check`) | Aucune dépendance incohérente |

Le test de charge réel a fait évoluer le backend de **1 à 5 instances**, maintenu
le maximum sous charge, puis obtenu le retour automatique de **5 à 1 instance**
après arrêt de la charge. Les seuils CPU étaient de 80 % et 10 %.
L'intervalle et la temporisation ont été temporairement ramenés à 2 et 5 secondes
pour ce scénario, puis les réglages habituels ont été rétablis.

Pendant le dernier cycle, **427 requêtes PATCH ont été envoyées : aucune erreur
HTTP**. Le conteneur d'autoscaling temporaire et la base PostgreSQL de test ont
été supprimés. Les tickets créés pour les essais ont été nettoyés et le volume
PostgreSQL existant de V1 a été conservé.

Les défauts détectés et corrigés pendant cette vérification sont :

- Les titres constitués d'espaces étaient acceptés et certaines valeurs nulles
  en modification produisaient une erreur 500. La validation renvoie maintenant
  une réponse 422 avant toute modification des données.
- Le retrait d'instances pouvait produire des erreurs 502/504 avec le groupe
  upstream dynamique. Le proxy résout maintenant le backend au moment des
  requêtes, avec un cache DNS d'une seconde et un délai de connexion court.
- Une modification pouvait être manquée pendant une déconnexion WebSocket.
  Le frontend recharge maintenant les tâches à chaque reconnexion ; le test
  navigateur reproduit ce cas.

Pour rendre l'IA vocale opérationnelle, remplacer `OPENAI_API_KEY` dans `.env`
par une clé valide puis recréer les services concernés :

```bash
docker compose up -d --no-deps --force-recreate voice-agent frontend
```

Pour réessayer le test vocal réel après ce changement :

```bash
TEST_BASE_URL=http://127.0.0.1:3000 TEST_REAL_VOICE=1 python3 -m unittest discover -s tests -p 'test_stack.py' -v
```

Les dépendances des tests sont dans `tests/requirements.txt`. La procédure pour
les autres suites et leurs variables d'environnement est documentée dans
`README.md`.
