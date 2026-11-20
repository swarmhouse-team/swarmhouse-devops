# Запуск, доступ и перезагрузка

Команды выполняются из корня репозитория. CD выкладывает этот каталог в `/opt/swarmhouse/swarmhouse-devops`: сначала `docker-compose.yml`, затем `docker-compose.monitoring.yml`.

## Что должно быть на сервере

- Linux-хост. `node-exporter` монтирует `/proc`, `/sys` и `/`. cAdvisor монтирует `/`, `/var/run`, `/sys`, `/var/lib/docker`, `/dev/disk` и запускается с `privileged: true`.
- Docker и Compose V2. Версия в репозитории не зафиксирована.
- Внешние сети `infra` и `monitoring`. Проверка: `docker network inspect infra` и `docker network inspect monitoring`. Создания сетей в репозитории нет.
- Файлы `.env`, `env/postgres.env`, `env/redis.env`, `env/grafana.env`, `env/postgres-exporter.env`, `env/redis-exporter.env`. В Git есть только `*.env.example`.
- Каталоги `data/postgres`, `data/redis`, `data/prometheus`, `data/grafana`. Для этих bind-монтирований задано `create_host_path: false`.

Лимиты контейнеров заданы в Compose и не являются измеренной потребностью хоста:

| Контейнер | CPU | Память |
| --- | --- | --- |
| `postgres` | 0.75 | 1g |
| `redis` | 0.25 | 256m |
| `prometheus` | 0.5 | 512m |
| `grafana` | 0.5 | 512m |
| `loki` | 0.5 | 512m |
| `alloy` | 0.25 | 256m |
| `cadvisor` | 0.25 | 256m |
| `node-exporter` | 0.25 | 128m |
| `postgres-exporter` | 0.25 | 128m |
| `redis-exporter` | 0.25 | 128m |

У `alloy-init` своих `cpus` и `mem_limit` нет. Общий якорь Compose их тоже не задаёт.

## Переменные

`.env.example` задаёт `TZ`, порты и теги образов. Секретов там нет. Пароли лежат в `env/*.env`, которые не коммитятся.

Обязательные ключи шаблонов, без значений:

- `env/postgres.env`: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_INITDB_ARGS`.
- `env/redis.env`: `REDIS_PASSWORD`.
- `env/grafana.env`: `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD`.
- `env/postgres-exporter.env`: `DATA_SOURCE_USER`, `DATA_SOURCE_PASS`.
- `env/redis-exporter.env`: `REDIS_PASSWORD`.

`POSTGRES_INITDB_ARGS` применяется только при первой инициализации пустого каталога данных.

`postgres-exporter` читает `DATA_SOURCE_URI` из `env/postgres-exporter.env`. В примере это `postgres:5432/app?sslmode=disable`, то же имя, что `POSTGRES_DB` в `env/postgres.env.example`. Роль и пароль — `DATA_SOURCE_USER` и `DATA_SOURCE_PASS`. Playbook при `deploy_services=true` создаёт отсутствующую роль и выдаёт `pg_monitor` и `CONNECT`. Существующий пароль роли не меняется.

`redis-exporter` ходит на `redis://redis:6379` и берёт пароль из `env/redis-exporter.env`. Этот пароль должен совпадать с `REDIS_PASSWORD` контейнера `redis`. Репозиторий совпадение не проверяет.

## Запуск

```bash
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.monitoring.yml up -d
```

`alloy` стартует после успешного завершения `alloy-init` (`condition: service_completed_successfully`). Init создаёт каталог хранилища в томе `alloy_data` и завершается. Политика `restart` у него переопределена на `no`.

Постоянные сервисы имеют `restart: unless-stopped`. После перезагрузки VPS Docker поднимает их сам, если контейнер не останавливали вручную. Это уже наблюдалось на сервере. Сам факт `Up` не подтверждает метрики, логи, дашборды и восстановление бэкапа.

## Состояние и логи

```bash
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.monitoring.yml ps
```

Healthcheck в Compose есть только у `postgres` и `redis`. У остальных сервисов мониторинга проверки здоровья нет: для них нормальный статус — `Up`, поля healthy не будет.

`alloy-init` должен быть `Exited` с кодом 0, а не `Up`. Имя контейнера в текущем файле — `alloy-init`. До появления `container_name` Compose называл его `monitoring-alloy-init-1`; такой контейнер на сервере уже завершался с кодом 0.

```bash
docker inspect --format '{{.Name}} {{.State.Status}} exit={{.State.ExitCode}}' alloy-init
docker compose -f docker-compose.yml logs --tail 100 postgres
docker compose -f docker-compose.monitoring.yml logs --tail 100 prometheus
```

Журнал Docker для `docker-compose.yml` режется `json-file`, `max-size` 10m, `max-file` 3. Для мониторинга — 100m и 3 файла. Это не срок хранения Loki.

## Остановка

Обычная остановка не удаляет тома и каталоги данных:

```bash
docker compose -f docker-compose.yml stop
docker compose -f docker-compose.monitoring.yml stop
```

`unless-stopped` после явного `stop` не поднимет контейнер при перезагрузке, пока его снова не запустить через `up -d`. Команду `docker compose down -v` в обычной остановке не использовать: `-v` удаляет тома `loki_data` и `alloy_data`.

## Обновление

Ручное обновление из корня репозитория:

```bash
git pull
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.monitoring.yml pull
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.monitoring.yml up -d
```

`git pull` сработает только если каталог — обычный клон с веткой. CD переводит каталог в detached HEAD на SHA `main` и при локальных изменениях отслеживаемых файлов останавливается. Затем он пересоздаёт `postgres` и `redis`, после них — сервисы мониторинга. `alloy-init` должен завершиться с кодом 0, остальные контейнеры мониторинга — быть в состоянии running. CD после запуска мониторинга ждёт `pg_up=1` у Prometheus на loopback и печатает предыдущий SHA. Автоматического возврата коммита нет. Healthcheck в Compose по-прежнему есть только у `postgres` и `redis`.

Смена файлов в `conf/` попадает в контейнер после пересоздания соответствующего сервиса. `up -d` пересоздаёт сервис, если изменился Compose или монтируемый файл.

## Доступ

Публикация только на loopback VPS:

| Сервис | Привязка |
| --- | --- |
| PostgreSQL | `127.0.0.1:${POSTGRES_PORT:-5432}` |
| Redis | `127.0.0.1:${REDIS_PORT:-6379}` |
| Prometheus | `127.0.0.1:${PROMETHEUS_PORT:-9090}` |
| Grafana | `127.0.0.1:${GRAFANA_PORT:-3000}` |

Loki, Alloy, cAdvisor и экспортёры порт на хост не публикуют. С других контейнеров сети `monitoring` они доступны по имени контейнера. PostgreSQL внутри контейнера слушает `listen_addresses = '*'`, Redis — `bind 0.0.0.0`, но с хоста порт открыт только на `127.0.0.1`.

Не пробрасывать эти порты на внешний интерфейс. С рабочей машины достаточно туннеля на уже опубликованные адреса. Имя хоста, пользователь и SSH-порт в репозитории не хранятся; CD берёт их из `DEPLOY_HOST`, `DEPLOY_USER` и `DEPLOY_PORT`:

```bash
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 -p <порт> <пользователь>@<хост>
```

После этого Grafana открывается как `http://127.0.0.1:3000`, Prometheus — `http://127.0.0.1:9090`. Логин Grafana читается из `env/grafana.env` (`GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD`). В `conf/grafana/grafana.ini` регистрация и анонимный доступ выключены. Вход — форма Grafana по `GF_SECURITY_ADMIN_USER` и `GF_SECURITY_ADMIN_PASSWORD`, поэтому в новом env `GF_AUTH_BASIC_ENABLED=true`. Публичного HTTP и TLS в репозитории нет, порты слушают loopback, поэтому `GF_SECURITY_COOKIE_SECURE=false`: иначе браузер по `http://127.0.0.1:3000` не сохранит сессию. `GF_AUTH_ANONYMOUS_ENABLED` должен оставаться `false`.

PostgreSQL и Redis с рабочей машины через такой туннель тоже попадут на loopback VPS. Для обычной работы приложений туннель не нужен: приложение в сети `infra` подключается к контейнерам `postgres:5432` и `redis:6379`.

## Проверка после перезагрузки VPS

Эти команды нужно выполнить вручную. Автоматического прогона в репозитории нет.

Docker и контейнеры:

```bash
docker info
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.monitoring.yml ps
docker inspect --format '{{.Name}} status={{.State.Status}} exit={{.State.ExitCode}}' \
  postgres redis prometheus grafana loki alloy cadvisor node-exporter postgres-exporter redis-exporter alloy-init
```

Ожидание по конфигурации, а не по непроверенному отчёту:

- `postgres` и `redis`: `running`. Healthcheck есть только у них; статус health смотреть отдельно: `docker inspect --format '{{.State.Health.Status}}' postgres redis`.
- Постоянные контейнеры мониторинга: `running`. Статуса healthy у них в Compose нет.
- `alloy-init`: `exited`, код 0.

Данные PostgreSQL. Команда использует переменные уже заданные внутри контейнера и не печатает пароль:

```bash
docker exec postgres sh -ec 'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker exec postgres sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT current_database(), now()"'
```

Redis:

```bash
docker exec redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h 127.0.0.1 ping'
```

Ожидаемый ответ healthcheck — `PONG`. Свежие метрики и логи проверяются отдельно, по [docs/monitoring.md](monitoring.md). Успешный `SELECT 1` не заменяет проверку бэкапа.
