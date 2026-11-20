"""Сравнение копий ключа и ответ slurp без rc. Без ключевого материала."""

import base64


def keys_conflict(remote_exists, local_exists, remote_checksum, local_checksum):
    """Условие tasks/actions_key.yml: оба файла есть и sha256 различается."""
    return bool(remote_exists and local_exists and remote_checksum != local_checksum)


def slurp_usable(result):
    """Успешный slurp узнаём по content, не по rc."""
    return "content" in result and result["content"] is not None


def decoded_equal(content_b64, raw_bytes):
    return base64.b64decode(content_b64) == raw_bytes


def main():
    same = "a" * 64
    assert keys_conflict(True, True, same, same) is False
    assert keys_conflict(True, True, "a" * 64, "b" * 64) is True
    assert keys_conflict(True, False, same, None) is False
    assert keys_conflict(False, True, None, same) is False

    payload = b"not-a-key\n"
    slurped = {
        "content": base64.b64encode(payload).decode("ascii"),
        "encoding": "base64",
        "source": "/opt/swarmhouse/secrets/github-actions/id_ed25519",
        "failed": False,
    }
    assert "rc" not in slurped
    assert slurp_usable(slurped) is True
    assert decoded_equal(slurped["content"], payload) is True
    assert decoded_equal(slurped["content"], payload + b"\n") is False

    missing = {"failed": True, "msg": "file not found"}
    assert slurp_usable(missing) is False

    print("same sha256 conflict", keys_conflict(True, True, same, same))
    print("different sha256 conflict", keys_conflict(True, True, "a" * 64, "b" * 64))
    print("missing local conflict", keys_conflict(True, False, same, None))
    print("slurp without rc usable", slurp_usable(slurped))
    print("ok")


if __name__ == "__main__":
    main()
