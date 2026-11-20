# Bootstrap VPS

Playbook готовит Ubuntu или Debian VPS к репозиторию. Контейнеры поднимаются только при `deploy_services=true`. Миграции и настройка GitHub Actions в playbook не входят.

Ansible запускается с Linux. На Windows это WSL. Отдельный Bash-скрипт вместо playbook не используется: `ssh-keygen` на Windows не нужен, пара ключа Actions создаётся на VPS.

## Что ставится

Поддерживаются только версии, для которых Docker публикует apt-репозиторий `stable`:

- Ubuntu 22.04, 24.04, 26.04, 26.10
- Debian 12, 13

Другие версии playbook останавливает. Полный upgrade ОС и перезагрузка не выполняются.

Если `docker --version` и `docker compose version` уже работают, пакеты Docker не переустанавливаются и источник apt не меняется. Если Docker есть, а Compose plugin нет, playbook останавливается.

Пользователь `deploy` создаётся без пароля и без sudo. Его добавляют в группу `docker`. Группа `docker` даёт доступ к демону и фактически равна root на этом хосте.

Каталоги:

- `/opt/swarmhouse`
- `/opt/swarmhouse/swarmhouse-devops` — checkout `https://github.com/swarmhouse-team/swarmhouse-devops.git`
- `/opt/swarmhouse/secrets/env` — канонические env, режим `0700`, владелец `deploy`
- `/opt/swarmhouse/secrets/github-actions` — ключ Actions, режим `0700`, владелец `root`

Compose по-прежнему читает `.env` и `env/*.env` внутри checkout. Эти пути — ссылки на `/opt/swarmhouse/secrets/env`. Отслеживаемые файлы секретов не получают. Если такой путь уже есть и это не ссылка на каталог секретов и не тот же файл, playbook останавливается.

В этом репозитории нет JWT, SMTP и API-секретов. Генерируются только пароли PostgreSQL, Redis и Grafana. `REDIS_PASSWORD` один и тот же в `redis.env` и `redis-exporter.env`. Пароль `postgres_exporter` отдельный. `JIRA_API_TOKEN` и `JIRA_USER` не генерируются.

Источник имени базы — `POSTGRES_DB` в `postgres.env`. Пример и новый файл задают `app`. `postgres-exporter` берёт ту же базу из `DATA_SOURCE_URI` в `postgres-exporter.env`. Роль `postgres_exporter` создаётся при `deploy_services=true`, если её ещё нет; существующий пароль роли не меняется. Новый `grafana.env` включает вход по паролю (`GF_AUTH_BASIC_ENABLED=true`), анонимный доступ выключен, cookie Secure выключен: опубликован только HTTP на loopback, TLS в репозитории нет.

## 1. Управляющая машина

Нужен Linux с Ansible 2.16+ и `ansible-core`. На управляющей машине ставится коллекция из `ansible/requirements.yml`:

```bash
ansible-galaxy collection install -r requirements.yml
```

Это `community.docker` для `docker_compose_v2`. На VPS коллекция не нужна.

В WSL пакеты ставятся внутри дистрибутива, не в Windows:

```bash
sudo apt update
sudo apt install ansible-core git
```

Каталог репозитория может лежать в `/mnt/c/...`. Локальные копии ключа и env — нет. `chmod` на диске Windows часто не даёт `0600`, и playbook тогда останавливается. `HOME` в WSL должен быть каталогом Linux, например `/home/<user>`, а не `/mnt/c/Users/...`.

Проверка host key не отключается. До первого запуска с управляющей машины должен быть известен ключ хоста VPS, например после обычного `ssh`.

`--check` сразу завершается ошибкой: в этом режиме нельзя честно проверить установку пакетов, генерацию ключей и паролей.

## 2. Inventory

Из каталога `ansible`:

```bash
cp inventory.example inventory.yml
```

`inventory.yml` в git не входит. В нём задаются адрес, SSH-порт, административный пользователь и путь к уже существующему ключу. Пароль sudo в файл не кладётся.

Тестовую VM не записывать в `inventory.yml` и не называть `swarmhouse-vps`. Для неё отдельный `inventory.test.yml` (тоже в `.gitignore`) с именем хоста `swarmhouse-test`. Копии ключа и env лежат в каталоге с именем хоста из inventory. Одинаковое имя смешает тестовые секреты с боевыми.

Образец тестового inventory — `ansible/inventory.test.example`:

```yaml
swarmhouse-test:
  ansible_host: 127.0.0.1
  ansible_port: 2222
  ansible_user: admin
  ansible_ssh_private_key_file: ~/.ssh/admin_virtual_box
  devops_git_version: "<ветка или тег>"
  allow_checkout_switch: false
```

`devops_git_version` — та же переменная, что в `group_vars/all.yml`. Там по умолчанию `main`, ветка CD. В тестовом inventory её переопределяют. Вместо `<ветка или тег>` подставьте реальное имя. Эта ветка или тег уже должны быть запушены в GitHub: playbook клонирует удалённый репозиторий, локальный незапушенный коммит на VM не попадёт.

Новый checkout создаётся сразу на этом ref, от пользователя `deploy`. Если каталог уже есть и HEAD другой, playbook останавливается. Переход на указанный ref — только с `allow_checkout_switch: true` (или `-e allow_checkout_switch=true`). По умолчанию флаг `false`. Перед переходом проверяются origin и чистое дерево отслеживаемых файлов. `reset --hard`, `clean`, force и stash не используются. Env, симлинки и секреты не удаляются. Если ref не запушен или в нём есть отслеживаемые env-файлы, переход не выполняется.

## 3. Административный ключ и sudo

`ansible_user` — уже существующий администратор, не `deploy`. `ansible_ssh_private_key_file` — его ключ.

Если sudo спрашивает пароль:

```bash
ansible-playbook bootstrap.yml --ask-become-pass
```

Пароль вводится в запрос Ansible и в репозиторий не записывается. Если у администратора уже есть passwordless sudo, флаг не нужен.

## 4. Запуск

Команды выполняются в каталоге `ansible` репозитория:

```bash
ansible-playbook bootstrap.yml --ask-become-pass
```

По умолчанию `deploy_services=false`: контейнеры не запускаются.

Тестовая VM, из каталога `ansible`. Inventory `inventory.test.yml` в git не входит:

```bash
ansible-playbook -i inventory.test.yml bootstrap.yml --ask-become-pass
ansible-playbook -i inventory.test.yml bootstrap.yml --ask-become-pass -e allow_env_sync=true
```

Перед включением запуска вручную допишите в `/opt/swarmhouse/secrets/env/grafana.env` реальные `JIRA_USER` и `JIRA_API_TOKEN`. Затем:

```bash
ansible-playbook -i inventory.test.yml bootstrap.yml --ask-become-pass -e deploy_services=true
```

Повторный запуск — та же команда. Секреты заново не генерируются. Конфликтующий контейнер playbook не пересоздаёт.

Боевой inventory — `inventory.yml`, и только после отдельного подтверждения:

```bash
ansible-playbook -i inventory.yml bootstrap.yml --ask-become-pass
ansible-playbook -i inventory.yml bootstrap.yml --ask-become-pass -e allow_env_sync=true
ansible-playbook -i inventory.yml bootstrap.yml --ask-become-pass -e deploy_services=true
```

Готовность после запуска: `postgres` и `redis` healthy, `alloy-init` exited 0, остальные контейнеры monitoring running, Prometheus отвечает `pg_up=1` на `127.0.0.1:9090`.

Последующий выклад кода — ручной запуск `.github/workflows/infra-cd.yml` на `main`. Он пересоздаёт сервисы без `down -v`, требует `pg_up=1` и не откатывает коммит сам. Предыдущий SHA печатается в журнале. Ручной возврат:

```bash
cd /opt/swarmhouse/swarmhouse-devops
git checkout --detach <предыдущий SHA>
docker compose -f docker-compose.yml up -d --wait --wait-timeout 120 postgres redis
docker compose -f docker-compose.monitoring.yml up -d
```

`down -v` не использовать. Миграций приложения этот репозиторий не содержит. Если схему менял другой репозиторий, возврат SHA её не отменит.

Проверка бэкапа входит в `deploy_services=true`, когда postgres уже healthy: дамп, восстановление в `restore_test_*`, удаление только этой базы. Каталог — `/opt/swarmhouse/swarmhouse-devops/data/backup`. Отдельный запуск скриптов из checkout:

```bash
./scripts/backup-postgres.sh
./scripts/restore-postgres-test.sh data/backup/<ГГГГ-ММ-ДД_ЧЧ-ММ-СС>
```

Вторая команда рабочую базу не открывает. Созданную ею тестовую базу удаляют отдельно, сверив имя.

Поднимаются только два проекта текущего репозитория, с их `name` и каталогом `/opt/swarmhouse/swarmhouse-devops`:

- `infrastructure_server` из `docker-compose.yml`: `postgres`, `redis`. Ожидание healthcheck, таймаут `deploy_wait_timeout` (120 секунд).
- `monitoring` из `docker-compose.monitoring.yml`: `alloy-init`, `prometheus`, `grafana`, `loki`, `alloy`, `cadvisor`, `node-exporter`, `postgres-exporter`, `redis-exporter`. Profiles в этих файлах нет. `alloy-init` считается готовым при `exited 0`, остальные — когда контейнер `running`.

Перед изменением контейнеров playbook проверяет обязательные параметры и печатает план. `JIRA_API_TOKEN` и `JIRA_USER` должны уже лежать в `grafana.env`: контакт `swarmhouse-jira` в provisioning без них не работает, отдельного выключателя Jira в репозитории нет. Пустые значения и заглушки example останавливают запуск до Docker. Playbook эти значения не придумывает.

Если `DATA_SOURCE_URI` не совпадает с `POSTGRES_DB`, анонимный доступ включён, basic-вход выключен или `GF_SECURITY_COOKIE_SECURE=true` при HTTP, запуск тоже останавливается. `-e allow_env_sync=true` переписывает только эти параметры и сохраняет остальные строки, включая пароли. Стандартный или пустой пароль Grafana синхронизация не заменяет.

Затем playbook ждёт healthcheck `postgres` и `redis`, создаёт отсутствующую базу `POSTGRES_DB` и отсутствующую роль из `DATA_SOURCE_USER`, выдаёт `pg_monitor` и `CONNECT`. Существующие база, роль и пароль не переименовываются и не сбрасываются. После мониторинга запуск успешен только если Prometheus на loopback вернул `pg_up=1`.

Если контейнер с тем же именем уже принадлежит другому project name, другому каталогу или его хеш Compose не совпадает с файлом, запуск останавливается. `compose down`, удаление volumes, `--force-recreate` и обновление уже скачанных образов не выполняются. Отсутствующий локальный образ может быть скачан один раз (`pull: missing`). При ошибке в отчёт попадает `docker compose ps` (имя и статус), без env и логов. Миграций приложения в этом репозитории нет, и playbook их не запускает.

Для старта создаются только отсутствующие сети `infra` и `monitoring` и пустые каталоги `data/postgres`, `data/redis`, `data/prometheus`, `data/grafana`. Существующие каталоги данных не переписываются.

Playbook на боевой VPS запускает человек. Из среды разработки он сам не стартует.

## 5. Куда попадают ключ и env

На VPS приватный ключ временно лежит в `/opt/swarmhouse/secrets/github-actions/id_ed25519` (`0600`, root). Публичный — рядом, в `id_ed25519.pub`, и в `~deploy/.ssh/authorized_keys`. Старые строки `authorized_keys` не удаляются.

На управляющей машине копии лежат вне репозитория:

```text
$HOME/.swarmhouse/vps/<имя хоста из inventory>/github-actions/id_ed25519
$HOME/.swarmhouse/vps/<имя хоста из inventory>/env/

Для тестовой VM имя хоста — `swarmhouse-test`, каталог `$HOME/.swarmhouse/vps/swarmhouse-test/`. Боевой хост в этот каталог не пишется.
```

Каталог `0700`, файлы `0600`. Если локальный файл уже есть и отличается, playbook останавливается и ничего не перезаписывает. Повторный запуск не создаёт новую пару и новые пароли.

Если публичный ключ уже есть, а приватный на VPS удалён cleanup-ом, это нормальное состояние. Новая пара не генерируется. Если приватный файл есть, а публичного нет, playbook останавливается и ключ не ротирует.

## 6. Что внести в GitHub вручную

Playbook в GitHub ничего не отправляет. Для `.github/workflows/infra-cd.yml` нужны:

| Куда | Имя | Что положить |
| --- | --- | --- |
| Secret | `DEPLOY_SSH_KEY` | содержимое локального `id_ed25519` |
| Secret | `DEPLOY_KNOWN_HOSTS` | строка `ssh-keyscan` для порта VPS |
| Variable | `DEPLOY_HOST` | адрес VPS |
| Variable | `DEPLOY_USER` | `deploy` |
| Variable | `DEPLOY_PORT` | SSH-порт |

`DEPLOY_KNOWN_HOSTS` снимается на управляющей машине отдельно, например `ssh-keyscan -p <порт> <хост>`. Playbook это не делает и вход Actions не проверяет.

Перед `deploy_services=true` в `grafana.env` вручную добавляются `JIRA_API_TOKEN` и `JIRA_USER`. Заглушки `api-token` и `email-jira` рабочими не являются. Если они уже лежат в существующем env, playbook останавливается и файл не переписывает. `DEPLOY_KNOWN_HOSTS` снимается с машины, которая уже доверяет ключу хоста, и сверяется с отпечатком в панели провайдера. Команда: `ssh-keyscan -p <порт> <хост>`. В workflow остаётся `StrictHostKeyChecking=yes`.

GitHub-hosted runner не открывает тестовую VM `127.0.0.1:2222`. CD против `swarmhouse-test` с этого runner не проверяется. Первый bootstrap Actions не требует.

## 7. Проверка входа deploy

После bootstrap, с управляющей машины:

```bash
ssh -i "$HOME/.swarmhouse/vps/<имя хоста из inventory>/github-actions/id_ed25519" \
  -p <порт> \
  -o IdentitiesOnly=yes \
  deploy@<хост>
```

Успешный вход этим ключом playbook не обещает: это отдельная проверка. Новая сессия нужна, чтобы группа `docker` была видна процессу.

## 8. Удалить временный ключ с VPS

Сначала сохраните локальную копию и проверьте вход. Затем из каталога `ansible`:

```bash
ansible-playbook cleanup-actions-key.yml --ask-become-pass -e confirm_actions_key_cleanup=true
```

Удаляется только `/opt/swarmhouse/secrets/github-actions/id_ed25519`. Публичный ключ и `authorized_keys` остаются. Если локальной копии нет или она не совпадает с серверной, файл на VPS не удаляется. Обычный `bootstrap.yml` cleanup не вызывает. Удаление — это `unlink`, не обещание затереть блоки на диске.

## 9. Повторный запуск и обрыв

Повторный запуск не меняет существующие ключи, пароли, env и checkout. При `allow_checkout_switch=false` checkout не переключается: нет `reset`, `clean` и stash. Если `HEAD` не равен `devops_git_version`, origin другой или в отслеживаемых файлах есть правки, playbook останавливается. Смена уже существующего checkout на другой запушенный ref возможна только при `allow_checkout_switch=true`. Уже запущенные контейнеры с тем же project name и тем же хешем Compose не пересоздаются. При `deploy_services=true` отсутствующие сервисы из явного списка создаются.

Если на VPS уже есть контейнер `postgres`, `redis` или `grafana` либо непустой `data/postgres`, `data/redis`, `data/grafana`, а соответствующего env нет, новые пароли не создаются. Неясное состояние Docker тоже останавливает playbook, а не считается пустым сервером.

Обрыв посередине не откатывает уже созданные каталоги. Следующий запуск продолжает с того, что уже совпадает с ожидаемым состоянием. Расходящиеся env и ключи он не перезаписывает.

## Бэкап PostgreSQL

Используется `scripts/backup-postgres.sh`. Второй системы бэкапов нет. Скрипт сам берёт `flock` на `scripts/.backup-postgres.lock`, пишет в `data/backup` относительно checkout и оставляет `KEEP=5` каталогов. Playbook это число не меняет: `backup_keep` должен быть `5`, иначе запуск останавливается.

Пользователь cron — `backup_user` (`deploy`). Расписание по умолчанию — каждый день в 03:15, переменные `backup_minute`, `backup_hour`, `backup_day`, `backup_month`, `backup_weekday`. Имя задачи постоянное: `swarmhouse-postgres-backup`. Другие строки crontab не удаляются. Если `backup-postgres.sh` уже упомянут в чужом задании, playbook останавливается и второе задание не создаёт.

На Ubuntu и Debian ставится пакет `cron`, сервис `cron` включается. После `healthy` у контейнера `postgres` скрипт запускается от `deploy`. Затем `scripts/restore-postgres-test.sh` восстанавливает этот дамп в новую базу `restore_test_*`, playbook проверяет `current_database()` и удаляет только её. Рабочая база не перезаписывается. Если любой шаг не прошёл, cron-задача не добавляется. Если postgres не запущен и `deploy_services=false`, тестовый бэкап и cron-задача пропускаются. Каталог `data/backup` лежит на том же VPS. Внешней копии репозиторий не создаёт: потеря диска VPS уничтожает и данные, и эти бэкапы. `KEEP=5`.

Задание вызывает абсолютный путь скрипта, рабочий каталог — checkout, `PATH` задан в строке cron. Ошибки дописываются в `/var/log/swarmhouse-postgres-backup.log`. Скрипт не печатает пароли.

## 10. Что bootstrap не делает

- не выполняет миграции приложения: их в этом репозитории нет, автоматического rollback схемы тоже нет;
- не делает `compose down`, не удаляет volumes и не пересоздаёт контейнеры принудительно;
- не меняет пароль уже существующей роли PostgreSQL и не переименовывает существующую базу;
- не настраивает firewall, `sshd`, домен и HTTPS;
- не добавляет GitHub Secrets и не проверяет вход Actions;
- не клонирует другие репозитории;
- не вывозит бэкап за пределы VPS.
