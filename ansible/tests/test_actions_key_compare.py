"""Проверка уникальности локальных каталогов."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "filter_plugins"))

from actions_key import local_dirs_conflict  # noqa: E402


def main():
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

    print("ok")


if __name__ == "__main__":
    main()
