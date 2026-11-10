import argparse
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv


def database_paths():
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    database = Path(os.getenv("APP_DATABASE", str(project_root / "data/m100.sqlite3"))).resolve()
    registry = Path(os.getenv("APP_REGISTRY", str(database.with_suffix(".registry.sqlite3"))))
    return database, registry


def snapshot(source, target):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy)


def backup(archive):
    database, registry = database_paths()
    if archive.exists():
        raise ValueError("Архив уже существует. Выберите новое имя.")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        snapshot(registry, staging / "registry.sqlite3")
        with closing(sqlite3.connect(staging / "registry.sqlite3")) as connection:
            projects = connection.execute("SELECT id, db_path FROM projects").fetchall()
        mapping = {}
        files = {"registry.sqlite3": staging / "registry.sqlite3"}
        snapshot(database, staging / "main.sqlite3")
        files["main.sqlite3"] = staging / "main.sqlite3"
        for index, (project_id, original) in enumerate(projects):
            relative = (
                "main.sqlite3"
                if Path(original).resolve() == database
                else f"objects/{project_id}.sqlite3"
            )
            mapping[project_id] = relative
            if relative not in files:
                target = staging / f"object-{index}.sqlite3"
                snapshot(Path(original).resolve(), target)
                files[relative] = target
        imports = database.parent / "imports"
        if imports.exists():
            for path in imports.iterdir():
                if path.is_file() and path.suffix in {".xlsx", ".json"}:
                    files[f"imports/{path.name}"] = path
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("manifest.json", json.dumps({"version": 1, "projects": mapping}))
            for name, path in files.items():
                output.write(path, name)


def restore(archive):
    database, registry = database_paths()
    root = database.parent
    if root.exists() and any(root.iterdir()):
        raise ValueError("Восстановление разрешено только в пустую папку данных")
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        if manifest.get("version") != 1:
            raise ValueError("Неподдерживаемая версия архива")
        names = source.namelist()
        targets = {}
        for name in names:
            if name == "manifest.json":
                continue
            target = (
                database
                if name == "main.sqlite3"
                else registry
                if name == "registry.sqlite3"
                else root / name
            )
            target = target.resolve()
            if (
                not target.is_relative_to(root)
                or Path(name).is_absolute()
                or ".." in Path(name).parts
            ):
                raise ValueError("Недопустимый путь в архиве")
            targets[name] = target
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(name))
    with closing(sqlite3.connect(registry)) as connection, connection:
        for project_id, relative in manifest["projects"].items():
            if relative not in targets:
                raise ValueError("В архиве отсутствует база объекта")
            connection.execute(
                "UPDATE projects SET db_path=? WHERE id=?", (str(targets[relative]), project_id)
            )


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("action", choices=("backup", "restore"))
    arguments.add_argument("archive", type=Path)
    options = arguments.parse_args()
    try:
        if options.action == "backup":
            backup(options.archive.resolve())
        else:
            restore(options.archive.resolve())
    except (ValueError, sqlite3.Error, OSError, zipfile.BadZipFile, KeyError):
        raise SystemExit("Операция не выполнена. Проверьте архив, пути и доступ к данным.")
    print("Операция с архивом завершена")


if __name__ == "__main__":
    main()
