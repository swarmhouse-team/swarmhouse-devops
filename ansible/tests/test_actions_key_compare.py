"""Решения filter_plugins/actions_key.py и ограничения копирования env."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "filter_plugins"))

from actions_key import env_copy_action, local_dirs_conflict  # noqa: E402

TASKS = ROOT / "tasks"


def main():
    same = "a" * 64
    assert env_copy_action(True, True, same, same) == "keep"
    assert env_copy_action(True, True, same, "b" * 64) == "conflict"
    assert env_copy_action(True, False) == "fetch"
    assert env_copy_action(False, True) == "block_generate"
    assert env_copy_action(False, False) == "absent"
    assert local_dirs_conflict(
        [
            "/home/admin/.swarmhouse/vps/swarmhouse-test",
            "/home/admin/.swarmhouse/vps/swarmhouse-vps",
        ]
    ) is False
    assert local_dirs_conflict(
        [
            "/home/admin/.swarmhouse/vps/swarmhouse-test",
            "/home/admin/.swarmhouse/vps/swarmhouse-test",
        ]
    ) is True

    env_text = (TASKS / "env.yml").read_text(encoding="utf-8")
    fetch = (TASKS / "fetch.yml").read_text(encoding="utf-8")
    assert "block_generate" in env_text
    assert env_text.index("Не создавать серверные env") < env_text.index("Сгенерировать пароль Redis")
    assert "force: true" not in fetch
    assert "conflict" in fetch

    print("env keep", env_copy_action(True, True, same, same))
    print("env conflict", env_copy_action(True, True, same, "b" * 64))
    print("env block", env_copy_action(False, True))
    print("ok")


if __name__ == "__main__":
    main()
