"""Проверки деплоя на искусственных данных. Секреты не печатаются."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "filter_plugins"))

from deploy_checks import (  # noqa: E402
    backup_dir_from_log,
    grafana_blockers,
    grafana_sync_updates,
    jira_problems,
    public_failure_text,
    restore_db_from_log,
    service_ready,
    sync_env,
)
from env_parse import parse_env  # noqa: E402


def main():
    assert jira_problems({}) == ["JIRA_USER", "JIRA_API_TOKEN"]
    assert jira_problems({"JIRA_API_TOKEN": "api-token", "JIRA_USER": "email-jira"}) == [
        "JIRA_USER",
        "JIRA_API_TOKEN",
    ]
    assert jira_problems({"JIRA_API_TOKEN": "external-token", "JIRA_USER": "ops@example.com"}) == []

    blocked = grafana_blockers(
        {
            "GF_AUTH_BASIC_ENABLED": "false",
            "GF_AUTH_ANONYMOUS_ENABLED": "false",
            "GF_SERVER_PROTOCOL": "http",
            "GF_SERVER_ROOT_URL": "http://127.0.0.1:3000",
            "GF_SECURITY_COOKIE_SECURE": "true",
            "GF_SECURITY_ADMIN_USER": "admin",
            "GF_SECURITY_ADMIN_PASSWORD": "not-a-default-value",
        }
    )
    assert "basic_disabled" in blocked
    assert "cookie_secure_on_http" in blocked
    assert "anonymous_enabled" not in blocked
    assert "admin_password_rejected" not in blocked
    assert grafana_sync_updates(blocked) == {
        "GF_AUTH_BASIC_ENABLED": "true",
        "GF_SECURITY_COOKIE_SECURE": "false",
    }
    assert grafana_sync_updates(["admin_password_rejected"]) == {}

    anonymous = grafana_blockers(
        {
            "GF_AUTH_BASIC_ENABLED": "true",
            "GF_AUTH_ANONYMOUS_ENABLED": "true",
            "GF_SERVER_PROTOCOL": "http",
            "GF_SECURITY_COOKIE_SECURE": "false",
            "GF_SECURITY_ADMIN_USER": "admin",
            "GF_SECURITY_ADMIN_PASSWORD": "not-a-default-value",
        }
    )
    assert anonymous == ["anonymous_enabled"]

    weak = grafana_blockers(
        {
            "GF_AUTH_BASIC_ENABLED": "true",
            "GF_AUTH_ANONYMOUS_ENABLED": "false",
            "GF_SERVER_PROTOCOL": "http",
            "GF_SECURITY_COOKIE_SECURE": "false",
            "GF_SECURITY_ADMIN_USER": "admin",
            "GF_SECURITY_ADMIN_PASSWORD": "admin",
        }
    )
    assert weak == ["admin_password_rejected"]

    original = "\n".join(
        [
            "GF_SECURITY_ADMIN_USER=admin",
            "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret",
            "GF_AUTH_BASIC_ENABLED=false",
            "GF_AUTH_ANONYMOUS_ENABLED=true",
            "GF_SECURITY_COOKIE_SECURE=true",
        ]
    )
    updated = sync_env(
        original,
        grafana_sync_updates(["basic_disabled", "anonymous_enabled", "cookie_secure_on_http"]),
    )
    assert "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret" in updated
    assert "GF_AUTH_BASIC_ENABLED=true" in updated
    assert "GF_SECURITY_COOKIE_SECURE=false" in updated
    assert "GF_AUTH_ANONYMOUS_ENABLED=false" in updated
    try:
        sync_env(original, {"DATA_SOURCE_PASS": "changed"})
    except ValueError:
        pass
    else:
        raise AssertionError("password sync was accepted")

    log = "[2026-01-01 00:00:00] Готово: /opt/swarmhouse/swarmhouse-devops/data/backup/2026-01-01_00-00-00 (1K)"
    assert backup_dir_from_log(log).endswith("/data/backup/2026-01-01_00-00-00")
    whiteout = (
        'failed to convert whiteout file "etc/alternatives/.wh.pager.1.gz": '
        "operation not permitted"
    )
    assert public_failure_text(whiteout) == whiteout
    assert public_failure_text("") == "не прочитана"
    assert public_failure_text("POSTGRES_PASSWORD=secret") == (
        "текст ошибки скрыт, потому что может содержать секрет"
    )
    assert service_ready("alloy-init", "exited 0") is True
    assert service_ready("alloy-init", "exited 1") is False
    assert service_ready("grafana", "running 0") is True
    assert service_ready("prometheus", "restarting 1") is False
    assert service_ready("loki", "") is False
    assert public_failure_text(
        {
            "msg": "One or more items failed",
            "results": [
                {"item": "grafana", "stdout": "restarting 1"},
                {"item": "prometheus", "msg": "stdout is undefined"},
            ],
        }
    ) == "grafana: restarting 1; prometheus: stdout is undefined"
    task = pathlib.Path(__file__).resolve().parents[1].joinpath("tasks", "deploy_up.yml").read_text(encoding="utf-8")
    assert "service_ready" in task
    assert "_task.result.stdout" in task
    assert "stdout is match" not in task
    grafana_local = "\n".join(
        [
            "GF_SECURITY_ADMIN_USER=admin",
            "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret",
            "GF_AUTH_BASIC_ENABLED=true",
            "GF_AUTH_ANONYMOUS_ENABLED=false",
            "GF_SERVER_PROTOCOL=http",
            "GF_SERVER_ROOT_URL=http://127.0.0.1:3000",
            "GF_SECURITY_COOKIE_SECURE=true",
        ]
    ) + "\n"
    grafana_updates = grafana_sync_updates(grafana_blockers(parse_env(grafana_local)))
    grafana_server = sync_env(grafana_local, grafana_updates)
    assert "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret" in grafana_server
    assert "GF_SECURITY_COOKIE_SECURE=false" in grafana_server
    assert "DATA_SOURCE_URI" not in grafana_server
    assert restore_db_from_log("Восстановление завершено. Тестовая база: restore_test_20260101_000000") == (
        "restore_test_20260101_000000"
    )
    assert restore_db_from_log("Тестовая база: otherdb") == ""

    print("jira missing", ",".join(jira_problems({})))
    print("grafana blockers", ",".join(blocked))
    print("password preserved", "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret" in updated)
    print("ok")


if __name__ == "__main__":
    main()
