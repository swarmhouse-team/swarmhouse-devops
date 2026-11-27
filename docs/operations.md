# Запуск, доступ и перезагрузка

Команды выполняются из корня репозитория. CD выкладывает этот каталог в `/opt/swarmhouse/swarmhouse-devops`: сначала `docker-compose.yml`, затем `docker-compose.monitoring.yml`.

GitHub Actions берёт параметры из Environment `production` и передаёт по SSH только SHA коммита. Принудительная команда ключа `deploy` проверяет SHA и запускает скрипт деплоя через sudo. Скрипт от root обновляет checkout и запускает Compose. Checkout, env и cron бэкапа принадлежат root.

`scripts/infra-deploy.sh` на сервер копирует Ansible. CD этот файл не обновляет: правка скрипта попадает на VPS только после повторного запуска playbook.

Кто может смержить в `main`, тот фактически получает root на VPS, потому что compose из `main` применяется от root. Нужен branch protection на `main`: обязательное ревью и запрет прямых пушей.

## Что должно быть на сервере

- Linux-хост. `node-exporter` монтирует `/proc`, `/sys` и `/`. cAdvisor монтирует `/`, `/var/run`, `/sys`, `/var/lib/docker`, `/dev/disk` и запускается с `privileged: true`.
- Docker и Compose V2. Версия в репозитории не зафиксирована.
- Внешние сети `infra` и `monitoring`. Compose их не создаёт. При `deploy_services=true` отсутствующие сети с драйвером `bridge` создаёт playbook; уже существующую сеть с другим драйвером он не меняет. Для ручного запуска: `docker network inspect infra` и `docker network inspect monitoring`.
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
| `cadvisor` | 1 | 256m |
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

`postgres-exporter` подключается к служебной базе `postgres` (`DATA_SOURCE_URI=postgres:5432/postgres?sslmode=disable`). Метрики `pg_stat_database` и `pg_stat_activity` кластерные, имя рабочей базы экспортёру не нужно. Имя рабочей базы задаётся только в `env/postgres.env` (`POSTGRES_DB`). Роль и пароль — `DATA_SOURCE_USER` и `DATA_SOURCE_PASS`. Playbook при `deploy_services=true` создаёт отсутствующую роль и выдаёт `pg_monitor` и `CONNECT` на базу `postgres`. Рабочую базу playbook не создаёт. Существующий пароль роли не меняется.

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

### Первый запуск приложения

Для первого запуска через bootstrap задайте `deploy_services=true` и `deploy_application=true`.
Ansible создаёт соседний каталог `/opt/swarmhouse/swarmhouse-project` с `docker-compose.yml` и
`.env`. Для приватных образов заранее настройте на VPS доступ root на чтение
`ghcr.io/swarmhouse-team/swarmhouse-{api,web}`. Образы `latest` должны быть опубликованы
workflow релиза с меткой версии OCI.

Bootstrap сверяет версию и образы обоих сервисов, выполняет миграции Prisma и проверяет
`/ru` и `/api/health` через Nginx. Подтверждённая версия записывается в `.env` и в
`/opt/swarmhouse/secrets/application/deployed-versions`. При повторном запуске bootstrap
сохранённая версия остаётся активной. Инфраструктурный CD обслуживает PostgreSQL, Redis и мониторинг.

Nginx слушает HTTP на `127.0.0.1:8080` по умолчанию. Для внешнего доступа подключите
TLS-прокси на хосте и укажите внешний HTTPS origin в `app_socket_origins` до первого bootstrap.
API выдаёт защищённые cookies в production, а разрешённые origins обязательны для Socket.IO.
Конфиг Nginx хранится в `conf/nginx/swarmhouse.conf`.

### Автоматическое обновление приложения

После успешного первого запуска задайте переменную репозитория приложения
`APP_DEPLOY_ENABLED=true`. В окружении `production` репозитория приложения
укажите `DEPLOY_HOST`, `DEPLOY_USER` и `DEPLOY_PORT`. Добавьте секреты
`DEPLOY_KNOWN_HOSTS` с проверенным ключом VPS и `APP_DEPLOY_SSH_KEY` с содержимым
файла `github-actions/app_id_ed25519`, который создаёт Ansible.
Для установки обработчика и скрипта на существующий VPS повторно выполните bootstrap.

После обновления обоих тегов `latest` workflow передаёт VPS конкретный тег релиза.
Сервер проверяет текущую пару контейнеров и историю Prisma перед обновлением.
Если есть новые миграции, файл `apps/api/prisma/rollback-allow` в релизе должен содержать
тег текущей production-версии на отдельной строке. Добавляйте его после проверки
работы старого API с новой схемой. При ошибке запуска или HTTP-проверок VPS возвращает
предыдущие образы и повторяет проверки. Выкладка в Actions получает статус ошибки
даже при успешном восстановлении. Миграции при возврате образов остаются применёнными.
Если Prisma сообщает об ошибке миграции, VPS оставляет текущие контейнеры и требует
ручной проверки базы.

### Ручной откат приложения

В репозитории приложения откройте **Actions → Roll back production application → Run workflow**
и выберите ветку `main`. Workflow использует окружение `production` и тот же SSH-ключ,
что и автоматическая выкладка. Повторите bootstrap на VPS после обновления скриптов,
чтобы SSH-обработчик принимал команду `rollback`.

Сервер выбирает наивысший тег ниже активного из журнала успешных выкладок. Он проверяет
схему PostgreSQL и пропускает несовместимые версии. Для образа, в котором нет части
применённых миграций, нужен допуск из `rollback-allow`, сохранённый при выкладке
именно этой схемы. Если записи о допуске ещё нет, откат доступен на версию с теми же
применёнными миграциями. При отсутствии подходящей версии workflow завершится ошибкой.

После переключения сервер проверяет страницу и API через Nginx, затем сохраняет
выбранный тег. Если проверки завершаются ошибкой, сервер пытается вернуть исходную
пару. Откат переключает образы API и Web. Схема БД и тег `latest` в GHCR сохраняются.

### Обновление инфраструктуры

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
