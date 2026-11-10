import json
import sqlite3
import zipfile

import pytest

from scripts.data_archive import backup, restore
from test_workspaces import client, create


def test_backup_restores_objects_and_rewrites_machine_paths(client, tmp_path, monkeypatch):
    object_id = create(client)
    archive = tmp_path / "transfer.zip"
    backup(archive)
    target = tmp_path / "restored" / "main.sqlite3"
    monkeypatch.setenv("APP_DATABASE", str(target))
    restore(archive)
    with sqlite3.connect(target.with_suffix(".registry.sqlite3")) as database:
        path = database.execute("SELECT db_path FROM projects WHERE id=?", (object_id,)).fetchone()[
            0
        ]
    assert path == str(target.parent / "objects" / f"{object_id}.sqlite3")
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM positions").fetchone()[0] == 62
    with pytest.raises(ValueError, match="пустую"):
        restore(archive)


def test_restore_rejects_paths_outside_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE", str(tmp_path / "safe" / "main.sqlite3"))
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps({"version": 1, "projects": {}}))
        output.writestr("../outside.txt", "invalid")
    with pytest.raises(ValueError, match="путь"):
        restore(archive)
    assert not (tmp_path / "outside.txt").exists()
