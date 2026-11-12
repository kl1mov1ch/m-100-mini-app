import argparse
import json
import os
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from contextlib import closing
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path, PureWindowsPath

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

SCHEMA = Path(__file__).resolve().parents[1] / "backend" / "postgres_schema.sql"
REGISTRY_TABLES = ("users", "projects", "shared_settings", "reminder_deliveries", "profile_avatars")
PROJECT_TABLES = ("positions", "entries", "reports", "audit", "settings", "day_snapshots")
OPTIONAL_TABLES = {"profile_avatars", "day_snapshots"}


def read_snapshot(archive, member, destination):
    with archive.open(member) as source, destination.open("wb") as target:
        while block := source.read(1024 * 1024):
            target.write(block)
    database = sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)
    database.row_factory = sqlite3.Row
    return database


def rows(database, table):
    if (
        table in OPTIONAL_TABLES
        and not database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    ):
        return []
    return [dict(row) for row in database.execute(f"SELECT * FROM {table}")]


def insert_rows(database, schema, table, records):
    if not records:
        return
    columns = tuple(records[0])
    statement = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    with database.cursor() as cursor:
        cursor.executemany(
            statement, (tuple(record[column] for column in columns) for record in records)
        )


def cents(amount):
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def import_project(database, source, ident, files_root):
    database.execute("SELECT set_config('journal.project_id', %s, true)", (ident,))
    amounts = defaultdict(Decimal)
    rates = {}
    counts = {}
    audit_max = 0
    for table in PROJECT_TABLES:
        records = rows(source, table)
        for record in records:
            record["project_id"] = ident
            if table == "positions":
                rates[record["id"]] = Decimal(str(record["rate"]))
            elif table == "entries":
                amounts[record["date"]] += (
                    Decimal(str(record["quantity"])) * rates[record["item_id"]]
                )
            elif table in {"audit", "day_snapshots"}:
                record["payload"] = Jsonb(json.loads(record["payload"]))
                if table == "audit":
                    audit_max = max(audit_max, record["id"])
            elif table == "settings" and record["key"] == "import_file_path" and record["value"]:
                filename = PureWindowsPath(record["value"]).name
                record["value"] = str(files_root / "imports" / filename)
        insert_rows(database, "journal", table, records)
        count = database.execute(
            sql.SQL("SELECT count(*) FROM journal.{} WHERE project_id=%s").format(
                sql.Identifier(table)
            ),
            (ident,),
        ).fetchone()[0]
        if count != len(records):
            raise ValueError(f"Row count mismatch for {ident}/{table}")
        counts[table] = count
    actual = database.execute(
        """SELECT e.date, sum(e.quantity * p.rate)
           FROM journal.entries e JOIN journal.positions p
             ON p.project_id=e.project_id AND p.id=e.item_id
           WHERE e.project_id=%s GROUP BY e.date""",
        (ident,),
    ).fetchall()
    if {day.isoformat(): cents(amount) for day, amount in actual} != {
        day: cents(amount) for day, amount in amounts.items()
    }:
        raise ValueError(f"Report totals differ for {ident}")
    return counts, audit_max


def grant_runtime_access(database, app_role):
    role = sql.Identifier(app_role)
    database.execute(sql.SQL("GRANT USAGE ON SCHEMA registry, journal TO {}").format(role))
    database.execute(sql.SQL("GRANT SELECT ON registry.schema_version TO {}").format(role))
    tables = sql.SQL(", ").join(sql.Identifier("registry", table) for table in REGISTRY_TABLES)
    database.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(tables, role)
    )
    database.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA journal TO {}"
        ).format(role)
    )
    database.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA journal TO {}").format(role))


def migrate(database, archive_path, app_role, files_root):
    role_allowed = database.execute(
        """SELECT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls
                  AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication
                  AND rolname <> current_user
           FROM pg_roles WHERE rolname=%s""",
        (app_role,),
    ).fetchone()
    if role_allowed != (True,):
        raise ValueError("Create a restricted PostgreSQL application role before migration")
    database.execute(SCHEMA.read_text(encoding="utf-8"))
    result = {"registry": {}, "projects": {}}
    if archive_path is not None:
        with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as temporary:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["version"] != 1:
                raise ValueError("Unsupported SQLite archive version")
            staging = Path(temporary).resolve()
            with closing(
                read_snapshot(archive, "registry.sqlite3", staging / "registry.sqlite3")
            ) as source:
                for table in REGISTRY_TABLES:
                    records = rows(source, table)
                    if table == "projects":
                        if set(manifest["projects"]) != {row["id"] for row in records}:
                            raise ValueError("Archive project manifest does not match the registry")
                        for record in records:
                            record["db_path"] = "project:" + record["id"]
                    insert_rows(database, "registry", table, records)
                    result["registry"][table] = len(records)
            audit_max = 0
            for index, (ident, member) in enumerate(manifest["projects"].items()):
                with closing(
                    read_snapshot(archive, member, staging / f"project-{index}.sqlite3")
                ) as source:
                    counts, largest_id = import_project(database, source, ident, files_root)
                    result["projects"][ident] = counts
                    audit_max = max(audit_max, largest_id)
            if audit_max:
                database.execute(
                    "SELECT setval(pg_get_serial_sequence('journal.audit', 'id'), %s)",
                    (audit_max,),
                )
    grant_runtime_access(database, app_role)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Initialize PostgreSQL and verify a SQLite archive migration"
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--archive", type=Path)
    inputs.add_argument("--empty", action="store_true")
    parser.add_argument("--app-role", default="m100_app")
    parser.add_argument("--files-root", type=Path, default=Path("/app/data"))
    args = parser.parse_args()
    connection_string = os.getenv("POSTGRES_OWNER_URL")
    if not connection_string:
        raise SystemExit("Set POSTGRES_OWNER_URL for the migration process")
    with psycopg.connect(connection_string) as database:
        result = migrate(database, args.archive, args.app_role, args.files_root)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
