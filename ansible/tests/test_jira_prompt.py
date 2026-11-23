"""Запрос Jira: решения и запись строк env. Секреты в вывод не попадают."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "filter_plugins"))

from deploy_checks import (  # noqa: E402
    apply_jira_lines,
    jira_answers_ready,
    jira_missing,
)
from env_parse import parse_env  # noqa: E402
from actions_key import env_copy_action  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TASK = (ROOT / "tasks" / "jira_prompt.yml").read_text(encoding="utf-8")
DEPLOY = (ROOT / "tasks" / "deploy.yml").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "bootstrap.yml").read_text(encoding="utf-8")


def main():
    full = {"JIRA_USER": "ops@example.com", "JIRA_API_TOKEN": "token-value"}
    assert jira_missing(full) == []

    assert jira_answers_ready(["JIRA_USER"], {"JIRA_USER": ""}) is False
    assert jira_answers_ready(["JIRA_USER"], {"JIRA_USER": "   "}) is False
    assert jira_answers_ready(["JIRA_USER", "JIRA_API_TOKEN"], {"JIRA_USER": "ops@example.com"}) is False
    assert jira_answers_ready(["JIRA_USER"], {"JIRA_USER": 'token"quoted'}) is False
    assert jira_answers_ready(["JIRA_USER"], {"JIRA_USER": "token with space"}) is False
    assert jira_answers_ready(["JIRA_USER"], {"JIRA_USER": "ops@example.com"}) is True

    original = "\n".join(
        [
            "GF_SECURITY_ADMIN_USER=admin",
            "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret",
            "GF_AUTH_BASIC_ENABLED=true",
        ]
    )
    try:
        apply_jira_lines(original, {"JIRA_USER": ""})
    except ValueError:
        pass
    else:
        raise AssertionError("empty value was written")
    assert "keep-this-secret" in original

    updated = apply_jira_lines(
        original,
        {"JIRA_USER": "ops@example.com", "JIRA_API_TOKEN": "token-value"},
    )
    parsed = parse_env(updated)
    assert parsed["GF_SECURITY_ADMIN_PASSWORD"] == "keep-this-secret"
    assert parsed["JIRA_USER"] == "ops@example.com"
    assert parsed["JIRA_API_TOKEN"] == "token-value"
    assert "GF_SECURITY_ADMIN_PASSWORD=keep-this-secret" in updated
    again = apply_jira_lines(updated, {})
    assert again == updated

    same = "a" * 64
    assert env_copy_action(True, True, same, "b" * 64) == "conflict"
    assert env_copy_action(True, True, same, same) == "keep"

    assert "vars_prompt" not in BOOTSTRAP
    assert "include_tasks: tasks/jira_prompt.yml" in DEPLOY
    assert DEPLOY.index("when: deploy_services | bool") < DEPLOY.index("jira_prompt.yml")
    assert "echo: false" in TASK
    assert "echo: true" in TASK
    assert "sys.stdin.isatty" not in TASK
    assert "jira_tty" not in TASK
    assert "delegate_to: localhost" in TASK
    assert "no_log: true" in TASK
    assert "diff: false" in TASK
    assert TASK.index("Остановить при расхождении") < TASK.index("Запросить JIRA_USER")
    assert TASK.index("Запросить JIRA_API_TOKEN") < TASK.index("Проверить введённые значения")
    assert TASK.index("Проверить введённые значения") < TASK.index("Записать только JIRA_USER")
    assert "mode: \"0600\"" in TASK

    print("empty refused", jira_answers_ready(["JIRA_API_TOKEN"], {"JIRA_API_TOKEN": ""}))
    print("conflict", env_copy_action(True, True, same, "b" * 64))
    print("ok")


if __name__ == "__main__":
    main()
