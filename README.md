# swarmhouse-devops

Репозиторий Docker Compose для PostgreSQL, Redis и мониторинга на VPS. Приложения сюда не входят: им отдаются базы и кэш по сети Docker, а интерфейсы публикации привязаны к loopback.

Рабочий каталог всех команд ниже — корень этого репозитория на сервере.

## Состав

Два проекта Compose:

| Файл | Проект | Сервисы |
| --- | --- | --- |
| `docker-compose.yml` | `infrastructure_server` | `postgres`, `redis` |
| `docker-compose.monitoring.yml` | `monitoring` | `prometheus`, `grafana`, `loki`, `alloy`, `alloy-init`, `node-exporter`, `cadvisor`, `postgres-exporter`, `redis-exporter` |

Сети `infra` и `monitoring` в Compose объявлены как внешние: файлы их не создают. Оба сервиса данных подключены к обеим сетям. Мониторинг подключён только к `monitoring`.

Роли:

- PostgreSQL и Redis хранят данные в `./data/postgres` и `./data/redis`.
- Экспортёры читают PostgreSQL, Redis, хост и контейнеры и отдают метрики Prometheus.
- Alloy читает логи контейнеров через сокет Docker и пишет их в Loki.
- Grafana показывает Prometheus и Loki. Дашборды лежат в `conf/grafana/dashboards` и попадают в папку Swarmhouse.

Подробности: [запуск и доступ](docs/operations.md), [мониторинг](docs/monitoring.md), [бэкап PostgreSQL](docs/backup.md).

## Структура

```text
docker-compose.yml
docker-compose.monitoring.yml
.env.example
env/*.env.example
conf/postgres/postgresql.conf
conf/redis/redis.conf
conf/prometheus/prometheus.yml
conf/loki/config.yml
conf/alloy/config.alloy
conf/grafana/
scripts/backup-postgres.sh
scripts/restore-postgres-test.sh
data/                  # на сервере, в Git не входит
```

`data/` в Git не коммитится. Loki и состояние Alloy лежат в томах Docker `loki_data` и `alloy_data`, не в `./data`.

## Быстрый старт

На сервере должны быть Docker и Compose V2: файлы используют `name`, bind с `create_host_path: false`, лимиты `cpus` и `mem_limit`. Минимальная версия Docker в репозитории не зафиксирована. Монтирование `/proc`, `/sys`, `/var/lib/docker` и привилегированный cAdvisor рассчитаны на Linux-хост.

```bash
docker network inspect infra
docker network inspect monitoring
```

Если сети ещё нет, её нужно создать до первого запуска. Репозиторий этого сам не делает:

```bash
docker network create infra
docker network create monitoring
```

Секреты не коммитятся. Шаблоны копируются в локальные файлы, значения задаются на сервере:

```bash
cp .env.example .env
cp env/postgres.env.example env/postgres.env
cp env/redis.env.example env/redis.env
cp env/grafana.env.example env/grafana.env
cp env/postgres-exporter.env.example env/postgres-exporter.env
cp env/redis-exporter.env.example env/redis-exporter.env
```

Каталоги данных с `create_host_path: false` Compose сам не создаст:

```bash
mkdir -p data/postgres data/redis data/prometheus data/grafana
```

```bash
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.monitoring.yml up -d
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.monitoring.yml ps
```

Порты наружу, все на `127.0.0.1`: PostgreSQL `${POSTGRES_PORT:-5432}`, Redis `${REDIS_PORT:-6379}`, Prometheus `${PROMETHEUS_PORT:-9090}`, Grafana `${GRAFANA_PORT:-3000}`. В `.env.example` это 5432, 6379, 9090 и 3000. С рабочей машины их открывают SSH-туннелем, не пробросом в интернет. Команды и проверки — в [docs/operations.md](docs/operations.md).

## GitHub Actions

[CI](.github/workflows/infra-ci.yml) проверяет оба Compose-файла. [CD](.github/workflows/infra-cd.yml) запускается вручную с `main` и в `/opt/swarmhouse/swarmhouse-devops` сначала обновляет `postgres` и `redis`, затем весь `docker-compose.monitoring.yml`. Перед мониторингом на сервере должны быть сеть `monitoring`, каталоги `data/prometheus` и `data/grafana`, а также `env/grafana.env`, `env/postgres-exporter.env` и `env/redis-exporter.env`.

Подготовка VPS — [docs/bootstrap.md](docs/bootstrap.md). Bootstrap ставит Docker, пользователя `deploy` и env. Контейнеры поднимаются только при `deploy_services=true`. Бэкап PostgreSQL ставится в cron через `scripts/backup-postgres.sh` после успешного тестового дампа.
