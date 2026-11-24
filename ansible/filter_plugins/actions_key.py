"""Проверка уникальности локальных каталогов."""


def local_dirs_conflict(paths):
    values = [str(item or "") for item in (paths or [])]
    if any(not item for item in values):
        return True
    return len(values) != len(set(values))


class FilterModule:
    def filters(self):
        return {"local_dirs_conflict": local_dirs_conflict}
