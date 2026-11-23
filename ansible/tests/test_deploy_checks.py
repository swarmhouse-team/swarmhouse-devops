"""Проверки деплоя на искусственных данных. Секреты не печатаются."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "filter_plugins"))

from deploy_checks import (  # noqa: E402
    backup_dir_from_log,
    jira_problems,
    public_failure_text,
    restore_db_from_log,
    service_ready,
)


def main():
    assert jira_problems({}) == ["JIRA_USER", "JIRA_API_TOKEN"]
    assert jira_problems({"JIRA_API_TOKEN": "api-token", "JIRA_USER": "email-jira"}) == [
        "JIRA_USER",
        "JIRA_API_TOKEN",
    ]
    assert jira_problems({"JIRA_API_TOKEN": "external-token", "JIRA_USER": "ops@example.com"}) == []

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
    assert restore_db_from_log("Восстановление завершено. Тестовая база: restore_test_20260101_000000") == (
        "restore_test_20260101_000000"
    )
    assert restore_db_from_log("Тестовая база: otherdb") == ""

    print("jira missing", ",".join(jira_problems({})))
    print("ok")


if __name__ == "__main__":
    main()
