#!/bin/sh
set -eu

export LC_ALL=C

SERVICE=backend
COMPOSE_PATH=${COMPOSE_PATH:-/workspace/docker-compose.yml}
MIN_REPLICAS=${MIN_REPLICAS:-1}
MAX_REPLICAS=${MAX_REPLICAS:-5}
CPU_SCALE_UP=${CPU_SCALE_UP:-80}
CPU_SCALE_DOWN=${CPU_SCALE_DOWN:-10}
SLEEP=${SLEEP:-10}
COOLDOWN=${COOLDOWN:-60}

log() {
  printf '%s - %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

for value in "$MIN_REPLICAS" "$MAX_REPLICAS" "$CPU_SCALE_UP" "$CPU_SCALE_DOWN" "$SLEEP" "$COOLDOWN"; do
  case "$value" in
    ''|*[!0-9]*) log "Configuration invalide : les valeurs doivent etre des entiers positifs ou nuls."; exit 1 ;;
    0|[1-9]*) ;;
    *) log "Configuration invalide : ne pas utiliser de zeros initiaux."; exit 1 ;;
  esac
done

if [ "$MIN_REPLICAS" -lt 1 ] || [ "$MAX_REPLICAS" -lt "$MIN_REPLICAS" ] \
  || [ "$CPU_SCALE_UP" -le "$CPU_SCALE_DOWN" ] || [ "$SLEEP" -lt 1 ]; then
  log "Configuration invalide : 1 <= MIN <= MAX, CPU_DOWN < CPU_UP et SLEEP >= 1 requis."
  exit 1
fi

# Read our own Compose label so `docker compose -p ... up` also works.
PROJECT_NAME=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "${HOSTNAME:?}")
if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" = '<no value>' ]; then
  log "Impossible de determiner le projet Compose de ce conteneur."
  exit 1
fi

docker compose version >/dev/null
log "Autoscaling de ${PROJECT_NAME}/${SERVICE} : ${MIN_REPLICAS}-${MAX_REPLICAS} instances."

scale_to() {
  log "Changement du nombre d'instances : $1"
  docker compose --project-name "$PROJECT_NAME" --file "$COMPOSE_PATH" \
    up --detach --no-deps --no-build --no-recreate --pull never \
    --scale "${SERVICE}=$1" "$SERVICE"
}

last_scale=$(date +%s)
trap 'exit 0' INT TERM

while true; do
  if ! container_ids=$(docker ps \
    --filter "label=com.docker.compose.project=$PROJECT_NAME" \
    --filter "label=com.docker.compose.service=$SERVICE" \
    --filter 'label=com.docker.compose.oneoff=False' \
    --format '{{.ID}}'); then
    log "Docker indisponible, nouvelle tentative au prochain cycle."
    sleep "$SLEEP"
    continue
  fi

  # Docker returns hexadecimal IDs; split them into individual CLI arguments.
  set -- $container_ids
  replicas=$#
  target=$replicas
  if [ "$replicas" -lt "$MIN_REPLICAS" ]; then
    target=$MIN_REPLICAS
  elif [ "$replicas" -gt "$MAX_REPLICAS" ]; then
    target=$MAX_REPLICAS
  else
    if ! samples=$(docker stats --no-stream --format '{{.CPUPerc}}' "$@"); then
      log "Mesure CPU indisponible, aucune modification."
      sleep "$SLEEP"
      continue
    fi

    # Never interpret missing or malformed stats as zero CPU usage.
    if ! average_cpu=$(printf '%s\n' "$samples" | awk -v expected="$replicas" '
      /^[0-9]+([.][0-9]+)?%$/ { sub(/%$/, ""); total += $0; count++; next }
      { invalid = 1 }
      END {
        if (invalid || count != expected) exit 1;
        printf "%.2f", total / count;
      }
    '); then
      log "Mesure CPU incomplete, aucune modification."
      sleep "$SLEEP"
      continue
    fi

    log "CPU moyen=${average_cpu}% | instances=${replicas}"
    now=$(date +%s)
    if [ "$((now - last_scale))" -ge "$COOLDOWN" ]; then
      direction=$(awk -v cpu="$average_cpu" -v up="$CPU_SCALE_UP" -v down="$CPU_SCALE_DOWN" \
        'BEGIN { print (cpu > up ? 1 : (cpu < down ? -1 : 0)) }')
      if [ "$direction" -eq 1 ] && [ "$replicas" -lt "$MAX_REPLICAS" ]; then
        target=$((replicas + 1))
      elif [ "$direction" -eq -1 ] && [ "$replicas" -gt "$MIN_REPLICAS" ]; then
        target=$((replicas - 1))
      fi
    fi
  fi

  if [ "$target" -ne "$replicas" ]; then
    if scale_to "$target"; then
      last_scale=$(date +%s)
    else
      log "Echec du changement d'echelle, nouvelle tentative au prochain cycle."
    fi
  fi
  sleep "$SLEEP"
done
