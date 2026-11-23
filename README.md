# swarmhouse-devops

Репозиторий Docker Compose для PostgreSQL, Redis и мониторинга на VPS. Приложения сюда не входят: им отдаются базы и кэш по сети Docker, а интерфейсы публикации привязаны к loopback.

Рабочий каталог ручных команд Compose — корень этого репозитория на сервере. Подготовка VPS — [docs/bootstrap.md](docs/bootstrap.md): по умолчанию `deploy_services=false`, контейнеры не запускаются.

## Как связано

Bootstrap готовит хост, checkout и секреты. Запуск контейнеров — отдельный шаг (`deploy_services=true` или ручной Compose). GitHub Actions только проверяет файлы и, отдельным ручным CD, выкладывает уже подготовленный checkout. Бэкап PostgreSQL — скрипт в репозитории; cron добавляет playbook и только после своего тестового прогона.

Потоки по текущим конфигам:

- метрики экспортёров и хоста забирает Prometheus (`conf/prometheus/prometheus.yml`), Grafana читает его как datasource;
- логи контейнеров Alloy снимает с сокета Docker и пишет в Loki, Grafana читает Loki;
- правила CPU и RAM и контакт Jira лежат в provisioning Grafana; токен Jira в Git не входит.

Подробности: [запуск](docs/operations.md), [мониторинг](docs/monitoring.md), [бэкап](docs/backup.md), [что уже подтверждено](docs/bootstrap.md#что-подтверждено).

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

Границы:

- bootstrap — хост, Docker, `deploy`, каталоги, публичный ключ Actions, checkout и env;
- `deploy_services=true` или ручной `docker compose up` — сами сервисы;
- GitHub — secrets и variables для CD, playbook их не создаёт;
- проверки после выкладки — отдельно от факта `Up`;
- бэкап и тестовое восстановление не заменяют копию вне этого VPS.

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
ansible/bootstrap.yml
.github/workflows/infra-ci.yml
.github/workflows/infra-cd.yml
data/                  # на сервере, в Git не входит
```

`data/` в Git не коммитится. Loki и состояние Alloy лежат в томах Docker `loki_data` и `alloy_data`, не в `./data`.

## Быстрый старт

На сервере должны быть Docker и Compose V2: файлы используют `name`, bind с `create_host_path: false`, лимиты `cpus` и `mem_limit`. Минимальная версия Docker в репозитории не зафиксирована. Монтирование `/proc`, `/sys`, `/var/lib/docker` и привилегированный cAdvisor рассчитаны на Linux-хост.

```bash
docker network inspect infra
docker network inspect monitoring
```

Compose объявляет сети внешними и сам их не создаёт. Для ручного запуска их создают заранее:

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

Команды ниже поднимают контейнеры. Это ручной запуск на машине, где стек действительно нужен, а не шаг по умолчанию и не команда для боевого inventory. На VPS обычный путь — bootstrap с `deploy_services=false`, пока запуск сервисов не подтверждён отдельно.

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

[CI](.github/workflows/infra-ci.yml) на `pull_request` и `push` в `main` гоняет `ansible/tests/test_*.py`, проверяет `docker compose config` обоих файлов на примерах env и скачивает образы из `docker-compose.yml` на runner. На VPS CI не заходит. [CD](.github/workflows/infra-cd.yml) запускается вручную с `main` и в `/opt/swarmhouse/swarmhouse-devops` сначала обновляет `postgres` и `redis`, затем весь `docker-compose.monitoring.yml`. CD требует `pg_up=1` и сам коммит не откатывает. Перед мониторингом на сервере должны быть сеть `monitoring`, каталоги `data/prometheus` и `data/grafana`, а также `env/grafana.env`, `env/postgres-exporter.env` и `env/redis-exporter.env`.

Подготовка VPS — [docs/bootstrap.md](docs/bootstrap.md). Bootstrap ставит Docker, пользователя `deploy` и env. Контейнеры поднимаются только при `deploy_services=true`. Бэкап PostgreSQL ставится в cron через `scripts/backup-postgres.sh` после успешного тестового дампа.
