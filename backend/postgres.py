import json
import os
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from threading import Lock

_pool = None
_pool_lock = Lock()


def enabled():
    return os.getenv("APP_STORAGE", "sqlite") == "postgres"


def project_id(reference):
    if not reference or not re.fullmatch(r"project:[A-Za-z0-9_-]{1,64}", str(reference)):
        raise RuntimeError("Project has no PostgreSQL reference")
    return str(reference).split(":", 1)[1]


def pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=5,
                num_workers=1,
                timeout=10,
                kwargs={
                    "row_factory": dict_row,
                    "options": "-c timezone=UTC -c statement_timeout=15000",
                },
                open=True,
            )
        return _pool


def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def compatible_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


class Row:
    def __init__(self, values):
        self.values = {key: compatible_value(value) for key, value in values.items()}

    def keys(self):
        return self.values.keys()

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values.values())[key]
        return self.values[key]

    def __iter__(self):
        return iter(self.values.values())


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row is not None else None

    def fetchall(self):
        return [Row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (Row(row) for row in self.cursor)


class Connection:
    def __init__(self, connection):
        self.connection = connection
        self.project = None

    def select_project(self, ident):
        self.connection.execute("SET LOCAL search_path TO journal, pg_catalog")
        self.connection.execute("SELECT set_config('journal.project_id', %s, true)", (ident,))
        self.project = ident

    def statement(self, query):
        parts = re.split(r"('(?:[^']|'')*')", query)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(
                r"(?<!:):([a-zA-Z_]\w*)", r"%(\1)s", parts[index].replace("?", "%s")
            )
            if self.project is not None:
                parts[index] = re.sub(
                    r"ON CONFLICT\s*\(", "ON CONFLICT (project_id,", parts[index], flags=re.I
                )
        return "".join(parts)

    def execute(self, query, parameters=None):
        if query.strip().upper() == "BEGIN IMMEDIATE":
            if self.project is None:
                raise RuntimeError("A report transaction needs a project")
            return Cursor(
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (self.project,)
                )
            )
        return Cursor(self.connection.execute(self.statement(query), parameters or None))

    def executemany(self, query, parameters):
        with self.connection.cursor() as cursor:
            cursor.executemany(self.statement(query), parameters)


@contextmanager
def connect(ident=None):
    with pool().connection() as raw_connection:
        database = Connection(raw_connection)
        if ident is None:
            raw_connection.execute("SET LOCAL search_path TO registry, pg_catalog")
        else:
            database.select_project(ident)
        yield database


def check_schema():
    with connect() as database:
        if database.execute("SELECT version FROM schema_version").fetchone()[0] != 1:
            raise RuntimeError("PostgreSQL schema version is incompatible")
