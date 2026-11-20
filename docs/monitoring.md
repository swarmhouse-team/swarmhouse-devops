# Мониторинг

Стек описан в `docker-compose.monitoring.yml` и `conf/`. Ниже только то, что задано файлами. Запуск контейнеров на VPS не означает, что каждая панель и каждый журнал уже проверены.

## Связка

```text
postgres  -- сеть monitoring --> postgres-exporter:9187 --+
redis     -- сеть monitoring --> redis-exporter:9121  --+--> prometheus:9090 --> grafana:3000
хост      --------------------> node-exporter:9100    --+
контейнеры ------------------> cadvisor:8080          --+

сокет Docker --> alloy --> loki:3100 --> grafana:3000
```

Prometheus забирает цели из `conf/prometheus/prometheus.yml` каждые 15 секунд. Общий `scrape_interval` — 15s. Для `node-exporter` и `cadvisor` интервал задан ещё раз, тоже 15s.

| job | Цель | Дополнительный лейбл |
| --- | --- | --- |
| `prometheus` | `localhost:9090` | нет |
| `grafana` | `grafana:3000` | нет |
| `node-exporter` | `node-exporter:9100` | `server=swarmhous` |
| `postgres` | `postgres-exporter:9187` | `server=swarmhous` |
| `redis` | `redis-exporter:9121` | `server=swarmhous` |
| `cadvisor` | `cadvisor:8080` | `server=swarmhous` |

Лейбл в файле записан как `swarmhous`, без последней буквы. Искать по `swarmhouse` эти серии не будут.

Grafana получает datasource provisioning из `conf/grafana/provisioning/datasources/datasources.yml`:

- `Prometheus`, uid `prometheus`, `http://prometheus:9090`, источник по умолчанию;
- `Loki`, uid `loki`, `http://loki:3100`.

Оба datasource нельзя править из UI (`editable: false`). Метрики самой Grafana включены в `conf/grafana/grafana.ini` (`[metrics] enabled = true`), поэтому job `grafana` есть чем заполнять.

Дашборды читаются из `/etc/grafana/dashboards` провайдером `swarmhouse` в папку Swarmhouse. Интервал обновления файлов — 30 секунд, удаление из UI выключено, правки из UI не записываются обратно (`allowUiUpdates: false`).

## Что собирается

Экспортёры:

- `node-exporter` смотрит procfs и sysfs хоста. Точки монтирования `/dev`, `/proc`, `/sys`, данные Docker и containerd из сборщика filesystem исключены флагом в Compose.
- `postgres-exporter` подключается по `DATA_SOURCE_URI`. Пример указывает базу `app`, как `POSTGRES_DB`. Роль задаётся `DATA_SOURCE_USER` / `DATA_SOURCE_PASS`. При `deploy_services=true` отсутствующая роль создаётся с `pg_monitor` и `CONNECT`.
- `redis-exporter` подключается к `redis://redis:6379`.
- cAdvisor запущен с `--docker_only=true`, `--housekeeping_interval=15s`, `--enable_load_reader=true`. Метрика `container_cpu_load_average_10s` без load reader в этом образе не появляется; флаг как раз для неё. В самом дашборде Docker Metrics панель `container_tasks_state` помечена как неработающая со ссылкой на ограничение cAdvisor. Отдельной проверки, что load reader на сервере отдаёт серии, в репозитории нет.

Логи. `conf/alloy/config.alloy` обнаруживает контейнеры через `/var/run/docker.sock` каждые 15 секунд и пушит их в `http://loki:3100/loki/api/v1/push`. Постоянные лейблы потока: `job=docker`, `server=swarmhous`. Из Docker добавляются:

- `container` — имя контейнера без ведущего `/`;
- `service_name` — лейбл Compose `com.docker.compose.service`;
- `compose_project` — лейбл `com.docker.compose.project`;
- `stream` — stdout или stderr.

Лейбла `host` Alloy не ставит. Лейбла `request_id` в конфигурации Alloy, Loki и дашбордов нет. Поиск по `request_id` не реализован.

## Хранение

- Prometheus: `--storage.tsdb.retention.time=15d` и `--storage.tsdb.retention.size=2GB`. Каталог на хосте — `./data/prometheus`. Сработает тот предел, который наступит раньше; отдельной проверки фактического объёма в репозитории нет.
- Loki: `retention_period: 168h` в `conf/loki/config.yml`, compactor включён, `retention_delete_delay: 2h`. Предела размера в конфиге нет. Данные в томе `loki_data`. Аутентификация Loki выключена (`auth_enabled: false`), но порт 3100 на хост не опубликован.
- Журнал Docker, не Loki: у мониторинга `max-size` 100m и 3 файла, у PostgreSQL и Redis — 10m и 3 файла.
- Позиции чтения Alloy лежат в томе `alloy_data` (`--storage.path=/data/storage`). Срок хранения этих позиций в конфиге не задан.

## Дашборды

Файлы в `conf/grafana/dashboards`, заголовок берётся из JSON:

| Файл | Заголовок | На что опирается |
| --- | --- | --- |
| `redis_metrics.json` | Redis metrics | job `redis`, переменная `instance` из `redis_up` |
| `docker_metrics.json` | Docker Metrics | job `cadvisor`, переменные `host_instance`, `compose_project`, `container_name` |
| `linux_metrics.json` | Linux metrics | метрики `node_*`, job выбирается в переменной из `node_uname_info` |
| `postgres_metrics.json` | PostgreSQL metrics | метрики `pg_*`; часть запросов фильтрует лейбл `release` |
| `docker_logs.json` | Docker Logs | Loki-запрос `{host=..., service_name=...}` |

Расхождение с конфигами, не проверенное на сервере:

- В `prometheus.yml` нет лейбла `release`. Панели PostgreSQL с `release="$release"` не совпадают со scrape. Часть других панелей того же файла `release` не использует.
- `docker_logs.json` фильтрует лейбл `host`. Alloy пишет `container`, `service_name`, `compose_project`, `stream`, `job`, `server`. Совпадение этого дашборда с текущим Alloy файлами не подтверждается.
- `linux_metrics.json` обращается к datasource по имени `${ds_prometheus}`. В provisioning источник назван `Prometheus`. Выбор источника на дашборде нужно проверить в UI.

Пока панели не открыты на сервере, наличие файла в каталоге не считать доказательством, что график живой.

## Как проверить свежие данные

На VPS, из корня репозитория. Prometheus слушает только loopback:

```bash
curl -fsS http://127.0.0.1:9090/api/v1/targets
curl -fsS --get http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=up'
```

У цели в `up` должно быть значение 1, а `health` в списке targets — `up`. Job для проверки те же, что в таблице выше: `prometheus`, `grafana`, `node-exporter`, `postgres`, `redis`, `cadvisor`. Время серии смотреть в поле `timestamp` ответа query: оно должно быть не старше пары интервалов scrape (15 секунд плюс допуск). Это ручная проверка.

Логи с хоста по порту Loki не запросить: порт не опубликован. В Grafana Explore, datasource Loki, запросы по лейблам Alloy:

```logql
{job="docker"}
{container="postgres"}
{service_name="redis"}
```

Пустой ответ означает, что цепочка ещё не подтверждена. Ошибки отправки смотреть так:

```bash
docker logs --tail 100 alloy
docker logs --tail 100 loki
```

## Уведомления

В `conf/grafana/provisioning` есть только `datasources` и `dashboards`. Правил Grafana Alerting, contact points и Alertmanager в репозитории нет. Prometheus тоже не подключает `rule_files`. Доставка email или Telegram не настроена и не проверялась.
