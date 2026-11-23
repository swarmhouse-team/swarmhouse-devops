"""Изолированные проверки parse_env и сборки stored_env. Без реальных секретов."""

import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "filter_plugins"))
from env_parse import parse_env


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def slurp_result(secret_name, text=None, failed=False):
    """Форма ответа ansible.builtin.slurp: content есть, поля rc нет."""
    result = {
        "item": {"checkout": "env/" + secret_name, "secret": secret_name},
        "failed": failed,
        "changed": False,
    }
    if text is not None:
        result["content"] = b64(text)
        result["encoding"] = "base64"
    return result


def assemble(results):
    """Та же развилка, что в set_fact stored_env после исправления."""
    stored = {}
    for item in results:
        parsed = parse_env(base64.b64decode(item["content"]).decode("utf-8")) if "content" in item else {}
        stored[item["item"]["secret"]] = parsed
    return stored


def old_assemble(results):
    """Прежняя развилка: нет rc считается ошибкой и даёт пустой словарь."""
    stored = {}
    for item in results:
        rc = item.get("rc", 1)
        parsed = parse_env(base64.b64decode(item["content"]).decode("utf-8")) if rc == 0 else {}
        stored[item["item"]["secret"]] = parsed
    return stored


def missing_keys(stored, required):
    missing = []
    for file_name, key in required:
        if key not in stored[file_name]:
            missing.append(file_name + ":" + key)
    return missing


def main():
    sample = "\n".join(
        [
            "# comment",
            "",
            "NAME=alpha",
            "EMPTY=",
            "PAIR=left=right",
            "  QUOTED=\"keep\"",
        ]
    )
    parsed = parse_env(sample)
    assert set(parsed) == {"NAME", "EMPTY", "PAIR", "QUOTED"}
    assert parsed["EMPTY"] == ""
    assert parsed["PAIR"] == "left=right"
    assert parsed["QUOTED"] == "keep"
    assert "comment" not in parsed

    dotenv = "\n".join(["# header", "TZ=Europe/Moscow", "POSTGRES_PORT=5432"])
    postgres = "\n".join(
        ["POSTGRES_DB=swarmhouse_db", "POSTGRES_USER=swarmhouse_admin", "POSTGRES_PASSWORD=not-a-real-secret"]
    )
    results = [
        slurp_result(".env", dotenv),
        slurp_result("postgres.env", postgres),
    ]
    assert "rc" not in results[0]

    stored = assemble(results)
    assert set(stored) == {".env", "postgres.env"}
    assert "TZ" in stored[".env"]
    assert "POSTGRES_PORT" in stored[".env"]
    assert "POSTGRES_DB" in stored["postgres.env"]
    assert "POSTGRES_PASSWORD" in stored["postgres.env"]

    required = [
        (".env", "TZ"),
        (".env", "POSTGRES_PORT"),
        (".env", "ABSENT"),
        ("postgres.env", "POSTGRES_DB"),
        ("postgres.env", "MISSING"),
    ]
    assert missing_keys(stored, required) == [".env:ABSENT", "postgres.env:MISSING"]

    broken = old_assemble(results)
    old_missing = missing_keys(
        broken,
        [(".env", "TZ"), (".env", "POSTGRES_PORT"), ("postgres.env", "POSTGRES_DB"), ("postgres.env", "POSTGRES_PASSWORD")],
    )
    assert old_missing == [
        ".env:TZ",
        ".env:POSTGRES_PORT",
        "postgres.env:POSTGRES_DB",
        "postgres.env:POSTGRES_PASSWORD",
    ]
    assert all(len(value) == 0 for value in broken.values())

    print("parser keys:", sorted(parsed))
    print("stored files:", sorted(stored))
    for name, data in sorted(stored.items()):
        print(name, type(data).__name__, "keys", len(data), sorted(data))
    print("old condition empty files:", sorted(broken))
    print("old missing:", old_missing)
    print("ok")


if __name__ == "__main__":
    main()
