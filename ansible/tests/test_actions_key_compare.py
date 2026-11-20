"""Решения filter_plugins/actions_key.py и ограничения playbook. Без боевых ключей."""

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "filter_plugins"))

from actions_key import (  # noqa: E402
    classify_actions_key,
    env_copy_action,
    local_dirs_conflict,
    same_public,
)

TASKS = ROOT / "tasks"
MATERIAL = "AAAAC3NzaC1lZDI1NTE5AAAAITestMaterialOnlyNotARealKey"
OTHER = "AAAAC3NzaC1lZDI1NTE5AAAAIAnotherMaterialOnlyNotARealKey"


def plan(**kwargs):
    return classify_actions_key(kwargs)


def main():
    pub_a = "ssh-ed25519 %s comment-a" % MATERIAL
    pub_b = "ssh-ed25519 %s comment-b" % MATERIAL
    pub_other = "ssh-ed25519 %s comment-a" % OTHER
    assert same_public(pub_a, pub_b) is True
    assert same_public(pub_a, pub_other) is False

    first = plan(local_private=False, local_public=False, server_private=False, server_public=False)
    assert first == {"action": "generate", "reason": "new_install"}
    again = plan(
        local_private=True,
        local_public=True,
        local_matches_derived="yes",
        server_private=False,
        server_public=False,
    )
    assert again["action"] == "install"
    assert again["reason"] == "no_legacy"
    assert plan(
        local_private=True,
        local_public=True,
        local_matches_derived="yes",
        server_private=False,
        server_public=False,
    )["action"] != "generate"

    recreated = plan(
        local_private=True,
        local_public=True,
        local_matches_derived="yes",
        server_private=False,
        server_public=False,
    )
    assert recreated["action"] == "install"

    assert plan(local_private=True, local_public=False)["reason"] == "missing_local_pub"
    assert plan(local_private=False, local_public=True)["reason"] == "orphan_local_pub"
    assert plan(
        local_private=True,
        local_public=True,
        local_matches_derived="no",
    )["reason"] == "local_pair_mismatch"
    assert plan(
        local_private=True,
        local_public=True,
        local_matches_derived="yes",
        server_private=True,
        server_public=True,
        server_pub_matches_local="yes",
        server_derived_matches_local="yes",
        server_halves_match="yes",
    )["reason"] == "legacy_left"

    different_legacy = plan(
        local_private=True,
        local_public=True,
        local_matches_derived="yes",
        server_private=True,
        server_public=True,
    )
    assert different_legacy == {"action": "install", "reason": "legacy_left"}
    assert plan(
        local_private=False,
        local_public=False,
        server_private=True,
        server_public=True,
    )["reason"] == "legacy_without_local"

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

    actions = (TASKS / "actions_key.yml").read_text(encoding="utf-8")
    env_text = (TASKS / "env.yml").read_text(encoding="utf-8")
    fetch = (TASKS / "fetch.yml").read_text(encoding="utf-8")
    assert "actions_key_migrate" not in actions
    assert "ansible.builtin.fetch:" not in actions
    assert '-f\n      - "{{ devops_actions_key }}"' not in actions
    assert '-f\n      - "{{ local_vps_dir }}/github-actions/id_ed25519"' in actions
    assert "exclusive: false" in actions
    assert "delegate_to: localhost" in actions
    assert "become: false" in actions
    assert 'creates: "{{ local_vps_dir }}/github-actions/id_ed25519"' in actions
    assert actions.index("classify_actions_key") < actions.index("authorized_key")
    assert "block_generate" in env_text
    assert env_text.index("Не создавать серверные env") < env_text.index("Сгенерировать пароль Redis")
    assert "force: true" not in fetch
    assert "conflict" in fetch

    ssh_keygen = "ssh-keygen"
    try:
        with tempfile.TemporaryDirectory() as temp:
            key = str(pathlib.Path(temp) / "id_ed25519")
            subprocess.run(
                [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-C", "comment-a", "-f", key],
                check=True,
            )
            derived = subprocess.run(
                [ssh_keygen, "-y", "-f", key],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            pub = pathlib.Path(key + ".pub").read_text(encoding="utf-8").strip()
            comment_only = derived.split()
            comment_only = " ".join(comment_only[:2] + ["comment-b"])
            assert same_public(pub, derived) is True
            assert same_public(pub, comment_only) is True
            private_before = pathlib.Path(key).read_bytes()
            subprocess.run([ssh_keygen, "-y", "-f", key], check=True, capture_output=True)
            assert pathlib.Path(key).read_bytes() == private_before
    except FileNotFoundError:
        print("ssh-keygen skipped")

    print("generate", first["reason"])
    print("repeat", again["action"])
    print("recreate", recreated["action"])
    print("orphan", plan(local_private=False, local_public=True)["reason"])
    print("legacy left", different_legacy["reason"])
    print("legacy without local", plan(local_private=False, server_private=True)["reason"])
    print("env keep", env_copy_action(True, True, same, same))
    print("env conflict", env_copy_action(True, True, same, "b" * 64))
    print("env block", env_copy_action(False, True))
    print("ok")


if __name__ == "__main__":
    main()
