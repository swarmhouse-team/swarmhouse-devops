#!/usr/bin/env bash
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root

[[ $EUID -eq 0 ]] || { echo "Запускать через sudo" >&2; exit 2; }
[[ $# -eq 1 ]] || { echo "Нужен ровно один аргумент" >&2; exit 2; }
DEPLOY_SHA="$1"
[[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: swarmhouse-infra-deploy <40-hex sha>" >&2; exit 2; }

CHECKOUT=/opt/swarmhouse/swarmhouse-devops
cd "$CHECKOUT"

exec 9>/run/swarmhouse-infra-deploy.lock
flock -n 9 || { echo "Деплой уже идёт" >&2; exit 1; }
# Lock уже создан с режимом 0600. Дальше checkout должен остаться читаемым для контейнеров.
umask 022

# Не затирать вручную изменённые отслеживаемые файлы.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "В отслеживаемых файлах есть локальные изменения. Деплой остановлен." >&2
  exit 1
fi

git fetch --prune origin \
  '+refs/heads/main:refs/remotes/origin/main'

git cat-file -e "${DEPLOY_SHA}^{commit}"
if [[ "$DEPLOY_SHA" != "$(git rev-parse origin/main)" ]]; then
  echo "SHA деплоя не совпадает с последним коммитом main." >&2
  exit 1
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
echo "Предыдущий коммит: $PREVIOUS_SHA"
echo "Выкладывается коммит: $DEPLOY_SHA"

git checkout --detach "$DEPLOY_SHA"

test -f docker-compose.yml
test -s .env
test -s env/postgres.env
test -s env/redis.env
test -f conf/postgres/postgresql.conf
test -f conf/redis/redis.conf
test -d data/postgres
test -d data/redis
test -f docker-compose.monitoring.yml
test -s env/grafana.env
test -s env/postgres-exporter.env
test -s env/redis-exporter.env
test -f conf/prometheus/prometheus.yml
test -f conf/loki/config.yml
test -f conf/alloy/config.alloy
test -f conf/grafana/grafana.ini
test -d conf/grafana/dashboards
test -d data/prometheus
test -d data/grafana

docker network inspect infra > /dev/null
docker network inspect monitoring > /dev/null
docker compose version
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.monitoring.yml config --quiet

# Образы скачиваются до перезапуска сервисов.
docker compose -f docker-compose.yml pull postgres redis

# Оба сервиса пересоздаются, чтобы применились bind-монтирования конфигов.
if ! docker compose -f docker-compose.yml up \
  -d \
  --force-recreate \
  --wait \
  --wait-timeout 120 \
  postgres redis; then
  docker compose -f docker-compose.yml ps
  echo "Деплой не удался. Логи смотрите на сервере." >&2
  echo "Предыдущий коммит: $PREVIOUS_SHA" >&2
  exit 1
fi

docker compose -f docker-compose.yml ps

docker compose -f docker-compose.monitoring.yml pull

if ! docker compose -f docker-compose.monitoring.yml up \
  -d \
  --force-recreate; then
  docker compose -f docker-compose.monitoring.yml ps
  echo "Деплой мониторинга не удался. Логи смотрите на сервере." >&2
  echo "Предыдущий коммит: $PREVIOUS_SHA" >&2
  exit 1
fi

alloy_init_status="$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' alloy-init)"
if [[ "$alloy_init_status" != "exited 0" ]]; then
  echo "alloy-init завершился не с кодом 0: ${alloy_init_status}" >&2
  docker compose -f docker-compose.monitoring.yml ps
  echo "Предыдущий коммит: $PREVIOUS_SHA" >&2
  exit 1
fi

for service in prometheus grafana loki alloy cadvisor node-exporter postgres-exporter redis-exporter; do
  state="$(docker inspect --format '{{.State.Status}}' "$service")"
  if [[ "$state" != "running" ]]; then
    echo "${service} в состоянии ${state}" >&2
    docker compose -f docker-compose.monitoring.yml ps
    echo "Предыдущий коммит: $PREVIOUS_SHA" >&2
    exit 1
  fi
done

prom_port="$(python3 -c 'import pathlib; env={k.strip(): v.strip() for line in pathlib.Path(".env").read_text().splitlines() if line and not line.startswith("#") and "=" in line for k, v in [line.split("=", 1)]}; print(env.get("PROMETHEUS_PORT", "9090"))')"
pg_up_ok=0
for _ in $(seq 1 24); do
  if python3 -c 'import json,sys,urllib.request; url="http://127.0.0.1:%s/api/v1/query?query=pg_up"%sys.argv[1]; body=json.load(urllib.request.urlopen(url, timeout=5)); values=[row.get("value",["",""])[1] for row in body.get("data",{}).get("result",[])]; sys.exit(0 if "1" in values else 1)' "$prom_port"; then
    pg_up_ok=1
    break
  fi
  sleep 5
done
if [[ "$pg_up_ok" != 1 ]]; then
  echo "pg_up не равен 1. Статуса контейнера недостаточно." >&2
  echo "Предыдущий коммит: $PREVIOUS_SHA" >&2
  exit 1
fi

docker compose -f docker-compose.monitoring.yml ps
echo "Деплой завершён: $DEPLOY_SHA"
echo "Автоматического отката нет. Предыдущий коммит: $PREVIOUS_SHA"
echo "В этом репозитории нет миграций приложения. Возврат на предыдущий SHA не отменяет изменения схемы, сделанные вне этого репозитория."
