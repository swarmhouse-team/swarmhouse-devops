# Bootstrap VPS

Playbook готовит Ubuntu или Debian VPS к репозиторию. Контейнеры поднимаются только при `deploy_services=true`. Миграции и настройка GitHub Actions в playbook не входят.

Ansible запускается с Linux. На Windows это WSL. Отдельный Bash-скрипт вместо playbook не используется. Пара ключа Actions создаётся на управляющей машине. На VPS в штатном сценарии попадает только её публичная часть, в `authorized_keys` пользователя `deploy`.

## Что ставится

Поддерживаются только версии, для которых Docker публикует apt-репозиторий `stable`:

- Ubuntu 22.04, 24.04, 26.04, 26.10
- Debian 12, 13

Другие версии playbook останавливает. Полный upgrade ОС и перезагрузка не выполняются.

Если в образе VPS уже есть Docker, удалите его до запуска bootstrap.

Пользователь `deploy` создаётся без пароля и без группы `docker`. Доступ к сокету Docker равен root, поэтому группы `docker` у него нет. `sudo` без пароля разрешён только для `/usr/local/sbin/swarmhouse-infra-deploy`. Других команд sudo нет.

Checkout `/opt/swarmhouse/swarmhouse-devops`, каталог env и cron бэкапа принадлежат root. Иначе `deploy` мог бы подменить compose или env, а скрипт применил бы их от root. Ansible копирует `scripts/infra-deploy.sh` в `/usr/local/sbin/swarmhouse-infra-deploy`. Правка скрипта попадает на сервер только после повторного запуска Ansible: CD сам root-скрипт не обновляет.

Серверы, настроенные до перехода на sudo, пересоздаются: playbook владельцев checkout, env и data не переносит и останавливается на первой проверке владельца.

Кто может смержить в `main`, тот фактически получает root на VPS: compose из `main` применяется от root. Нужен branch protection на `main`: обязательное ревью и запрет прямых пушей.

Каталоги:

- `/opt/swarmhouse`
- `/opt/swarmhouse/swarmhouse-devops` — checkout `https://github.com/swarmhouse-team/swarmhouse-devops.git`, владелец `root`, режим `0755`
- `/opt/swarmhouse/secrets/env` — канонические env, режим `0700`, владелец `root`
Compose по-прежнему читает `.env` и `env/*.env` внутри checkout. Эти пути — ссылки на `/opt/swarmhouse/secrets/env`. Отслеживаемые файлы секретов не получают. Если такой путь уже есть и это не ссылка на каталог секретов и не тот же файл, playbook останавливается.

В этом репозитории нет JWT, SMTP и API-секретов. Генерируются только пароли PostgreSQL, Redis и Grafana. `REDIS_PASSWORD` один и тот же в `redis.env` и `redis-exporter.env`. Пароль `postgres_exporter` отдельный. `JIRA_API_TOKEN` и `JIRA_USER` не генерируются.

Имя рабочей базы задаётся только в `env/postgres.env` (`POSTGRES_DB`). `postgres-exporter` подключается к служебной базе `postgres` (`DATA_SOURCE_URI=postgres:5432/postgres?sslmode=disable`). Метрики `pg_stat_database` и `pg_stat_activity` кластерные, имя рабочей базы экспортёру не нужно. Роль `postgres_exporter` создаётся при `deploy_services=true`, если её ещё нет; существующий пароль роли не меняется. Новый `grafana.env` включает вход по паролю (`GF_AUTH_BASIC_ENABLED=true`), анонимный доступ выключен, cookie Secure выключен: опубликован только HTTP на loopback, TLS в репозитории нет.

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
```

`devops_git_version` — та же переменная, что в `group_vars/all.yml`. Там по умолчанию `main`, ветка CD. В тестовом inventory её переопределяют. Вместо `<ветка или тег>` подставьте реальное имя. Эта ветка или тег уже должны быть запушены в GitHub: playbook клонирует удалённый репозиторий, локальный незапушенный коммит на VM не попадёт.

Новый checkout создаётся сразу на этом ref, от пользователя `root`. Если каталог уже есть и HEAD другой, playbook останавливается. Существующий checkout не переключается: нет `reset`, `clean`, force и stash. Env, симлинки и секреты не удаляются.

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

Вопросы про Jira можно пропустить через `-e jira_user= -e jira_api_token=`.

Тестовая VM, из каталога `ansible`. Inventory `inventory.test.yml` в git не входит:

```bash
ansible-playbook -i inventory.test.yml bootstrap.yml --ask-become-pass
```

При запуске bootstrap Ansible запрашивает `JIRA_USER` и `JIRA_API_TOKEN` без отображения ввода. Оба поля можно оставить пустыми. Значения записываются только при создании нового `grafana.env`. Запуск сервисов включается отдельно:

```bash
ansible-playbook -i inventory.test.yml bootstrap.yml --ask-become-pass -e deploy_services=true
```

Повторный запуск — та же команда. Секреты заново не генерируются. Конфликтующий контейнер playbook не пересоздаёт.

Боевой inventory — `inventory.yml`, и только после отдельного подтверждения:

```bash
ansible-playbook -i inventory.yml bootstrap.yml --ask-become-pass
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

Перед изменением контейнеров playbook проверяет конфигурацию Compose и печатает план. При пустых реквизитах Jira уведомления в Jira работать не будут.

Чтобы добавить или заменить реквизиты Jira на работающем VPS, откройте `sudoedit /opt/swarmhouse/secrets/env/grafana.env`, измените строки `JIRA_USER` и `JIRA_API_TOKEN`, затем из checkout выполните `sudo docker compose -f docker-compose.monitoring.yml up -d --force-recreate grafana`.

Затем playbook ждёт healthcheck `postgres` и `redis` и создаёт отсутствующую роль из `DATA_SOURCE_USER`. Роли выдаются `pg_monitor` и `CONNECT` на служебную базу `postgres`. Рабочую базу playbook не создаёт: её создаёт образ PostgreSQL из `POSTGRES_DB` при первой инициализации каталога данных. Существующие роль и пароль не переименовываются и не сбрасываются. Проверка `SELECT 1` идёт в базе `postgres`. После мониторинга запуск успешен только если Prometheus на loopback вернул `pg_up=1`.

Если контейнер с тем же именем уже принадлежит другому project name, другому каталогу или его хеш Compose не совпадает с файлом, запуск останавливается. `compose down`, удаление volumes, `--force-recreate` и обновление уже скачанных образов не выполняются. Отсутствующий локальный образ может быть скачан один раз (`pull: missing`). При ошибке в отчёт попадает `docker compose ps` (имя и статус), без env и логов. Миграций приложения в этом репозитории нет, и playbook их не запускает.

Для старта создаются только отсутствующие сети `infra` и `monitoring`. Каталог `data` принадлежит `root`, режим `0755`. Корни `data/postgres`, `data/redis`, `data/prometheus` и `data/grafana` пользователю `deploy` не отдаются. Числовой UID в репозиторий не записан. У PostgreSQL playbook вызывает `id postgres` внутри используемого образа. У Redis, Prometheus и Grafana — `id` от пользователя по умолчанию этого образа. Режим только у корня каталога — `0700`, без рекурсивного `chown`. Пути mount и `PGDATA` не меняются. Повторный запуск не возвращает эти корни пользователю `deploy`. Перед стартом проверяется проход этого пользователя в каталог; для PostgreSQL — ещё и путь до `PGDATA`. На сервере этот шаг пока не подтверждался: последний прогон тестовой VM шёл с `deploy_services=false` и каталоги данных не готовил.

Playbook на боевой VPS запускает человек. Из среды разработки он сам не стартует.

## 5. Куда попадают ключ и env

Канонический приватный ключ Actions лежит только на управляющей машине:

```text
$HOME/.swarmhouse/vps/<имя хоста из inventory>/github-actions/id_ed25519
```

Каталог `0700`, приватный файл `0600`. Пара создаётся локально, только если этого файла ещё нет. Повторный запуск ту же пару не перезаписывает. На VPS в штатном сценарии приватный ключ не копируется. Публичная часть добавляется в `~deploy/.ssh/authorized_keys` без `exclusive`, остальные ключи deploy сохраняются. Ключ администратора, которым Ansible входит на сервер, не меняется.

`DEPLOY_SSH_KEY` — содержимое этого локального приватного файла. `DEPLOY_KNOWN_HOSTS` — host key SSH самого сервера. Это разные ключи. Установка публичного ключа не означает, что вход Actions уже проверен.

Тестовый хост `swarmhouse-test` и боевой хост получают разные каталоги, потому что в путь входит `inventory_hostname`. Одинаковый `local_vps_dir` у двух хостов одного запуска playbook останавливает.

Новое независимое тестовое окружение — это другой каталог, а не новая метка времени на каждом запуске. Либо другое имя хоста в inventory, либо свой `local_vps_dir` в host vars. Старые артефакты можно убрать из рабочего пути вручную, не удаляя их:

```bash
mv "$HOME/.swarmhouse/vps/swarmhouse-test" \
  "$HOME/.swarmhouse/vps/swarmhouse-test.previous"
```

Следующие повторы снова пишут в `swarmhouse-test`, а не в каталог с датой.

Если локально есть только `.pub`, playbook останавливается и новую пару не создаёт. Если приватный файл есть, а `.pub` нет, публичная часть восстанавливается из приватного ключа, сам приватный файл не меняется. Несовпадение типа или key material останавливает запуск. Разный комментарий при том же ключе конфликтом не считается.

Потеря каталога на controller не лечится скачиванием ключа с VPS. Нужна защищённая резервная копия либо отдельное решение о смене ключа. После смены обновите `DEPLOY_SSH_KEY` и проверьте вход до отзыва старого ключа.

Канонический приватный ключ — локальный файл на управляющей машине. Bootstrap ставит его публичную часть в `authorized_keys` и не кладёт приватный ключ на VPS.

Файлы в `~/.swarmhouse/vps/<host>/passwords/` используются только при создании нового env. На работающем сервере действующие пароли хранятся в `/opt/swarmhouse/secrets/env/`. Для восстановления берите локальную копию env из `~/.swarmhouse/vps/<host>/env/`. При повторном запуске bootstrap обновляет эту копию с сервера и сохраняет режим `0600`.

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

`DEPLOY_KNOWN_HOSTS` снимается с машины, которая уже доверяет ключу хоста, и сверяется с отпечатком в панели провайдера. Команда `ssh-keyscan -p <порт> <хост>`. В workflow остаётся `StrictHostKeyChecking=yes`.

GitHub-hosted runner не открывает тестовую VM `127.0.0.1:2222`. CD против `swarmhouse-test` с этого runner не проверяется. Первый bootstrap Actions не требует.

## 7. Проверка входа deploy

После bootstrap, с управляющей машины:

```bash
ssh -i "$HOME/.swarmhouse/vps/<имя хоста из inventory>/github-actions/id_ed25519" \
  -p <порт> \
  -o IdentitiesOnly=yes \
  deploy@<хост>
```

Успешный вход этим ключом playbook не обещает: это отдельная проверка. У `deploy` нет группы `docker`. Общего sudo нет. С этой сессии разрешена одна команда: `sudo -n /usr/local/sbin/swarmhouse-infra-deploy <40-hex SHA>`. `sudo -n bash` и `docker ps` должны отказать.

## 8. Повторный запуск и обрыв

Повторный запуск не создаёт новую пару Actions, не перезаписывает пароли, env и checkout. После пересоздания VM с тем же `local_vps_dir` на сервер ставится прежняя публичная часть. Существующий checkout не переключается: нет `reset`, `clean` и stash. Если `HEAD` не равен `devops_git_version`, origin другой или в отслеживаемых файлах есть правки, playbook останавливается. Уже запущенные контейнеры с тем же project name и тем же хешем Compose не пересоздаются. При `deploy_services=true` отсутствующие сервисы из явного списка создаются.

Если `data/postgres` непустой, а `postgres.env` отсутствует, bootstrap останавливается. До повторного запуска восстановите `/opt/swarmhouse/secrets/env/postgres.env` из локальной копии env.

При обрыве уже созданные каталоги и серверные env сохраняются. Повторный запуск создаёт недостающие файлы и обновляет локальные копии env с VPS.

## Бэкап PostgreSQL

Используется `scripts/backup-postgres.sh`. Второй системы бэкапов нет. Скрипт сам берёт `flock` на `scripts/.backup-postgres.lock`, пишет в `data/backup` относительно checkout и оставляет `KEEP=5` каталогов. Playbook скрипт не переписывает.

Пользователь cron — `root` (`backup_user`): скрипт делает `docker exec`. Задача с тем же именем в crontab `deploy` удаляется. Расписание по умолчанию — каждый день в 03:15, переменные `backup_minute`, `backup_hour`, `backup_day`, `backup_month`, `backup_weekday`. Имя задачи постоянное: `swarmhouse-postgres-backup`. Другие строки crontab не удаляются. Если `backup-postgres.sh` уже упомянут в чужом задании, playbook останавливается и второе задание не создаёт.

На Ubuntu и Debian ставится пакет `cron`, сервис `cron` включается. После `healthy` у контейнера `postgres` скрипт запускается от `root`. Затем `scripts/restore-postgres-test.sh` восстанавливает этот дамп в новую базу `restore_test_*`, playbook проверяет `current_database()` и удаляет только её. Рабочая база не перезаписывается. Если любой шаг не прошёл, cron-задача не добавляется. Если postgres не запущен и `deploy_services=false`, тестовый бэкап и cron-задача пропускаются. Каталог `data/backup` лежит на том же VPS. Внешней копии репозиторий не создаёт: потеря диска VPS уничтожает и данные, и эти бэкапы. `KEEP=5`.

Задание вызывает абсолютный путь скрипта, рабочий каталог — checkout, `PATH` задан в строке cron. Ошибки дописываются в `/var/log/swarmhouse-postgres-backup.log`. Скрипт не печатает пароли.

## Что подтверждено

Это границы проверок, а не обещание, что стек готов.

Исторический отчёт по действующему VPS, не повторявшийся при последней правке документации: PostgreSQL и Redis подняты Compose; стек Grafana, Prometheus, Loki, Alloy, Node Exporter, cAdvisor, postgres-exporter и redis-exporter описан и, по тому отчёту, запускался; после перезагрузки VPS постоянные контейнеры поднимались, у PostgreSQL, Redis и cAdvisor был статус healthy; уведомление в Jira и правила высокой загрузки CPU и низкой доступной RAM тогда проверялись. Скрипты бэкапа и тестового восстановления лежат в Git с правом исполнения. Успешное восстановление конкретной базы этим фактом не доказано.

Отдельная тестовая VM `swarmhouse-test`, повторный bootstrap: `ok=83`, `changed=0`, `unreachable=0`, `failed=0`, `skipped=131`, `deploy_services=false`. `changed=0` значит, что уже существующие Docker, пользователь `deploy` и checkout менять не пришлось. Checkout был `/opt/swarmhouse/swarmhouse-devops`, отчёт показал версию `swarmhouse-53`. Контейнеров проекта не было. Env лежали в `/opt/swarmhouse/secrets/env`, отчёт указал режим `0600` и владельца `deploy`. Приватный файл Actions на VM ещё оставался. Вход Actions, тестовый бэкап и cron не выполнялись.

Этот прогон не подтверждает чистую установку после последних правок playbook, запуск сервисов, работу Actions и бэкап на этой VM.

## Если bootstrap остановился

Короткие случаи, которые уже встречались в этом playbook. Секреты и ключи при разборе не печатать и не перезаписывать.

- Результат цикла лежит во вложенном элементе. У `stat` или `command` с `register` и `loop` поля вроде `stat` и `stdout` читаются как `item.stat` и `item.item`, а не как будто сам элемент — исходный словарь списка. Ошибка вида «dict object has no attribute» на таком поле означает неверный уровень, а не отсутствие файла.
- Канонический приватный ключ Actions — локальный файл на управляющей машине. Если локальные половины пары не совпадают, playbook останавливается и файлы не перезаписывает. Приватный ключ на VPS не кладётся.

## 9. Что bootstrap не делает

- не выполняет миграции приложения: их в этом репозитории нет, автоматического rollback схемы тоже нет;
- не делает `compose down`, не удаляет volumes и не пересоздаёт контейнеры принудительно;
- не меняет пароль уже существующей роли PostgreSQL и не переименовывает существующую базу;
- не настраивает firewall, `sshd`, домен и HTTPS;
- не добавляет GitHub Secrets и не проверяет вход Actions;
- не клонирует другие репозитории;
- не вывозит бэкап за пределы VPS.
