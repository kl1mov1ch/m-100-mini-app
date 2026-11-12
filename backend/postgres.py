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
            from psycopg.conninfo import conninfo_to_dict
            from sqlalchemy import URL, create_engine

            values = conninfo_to_dict(os.environ["DATABASE_URL"])
            url = URL.create(
                "postgresql+psycopg",
                username=values.pop("user", None),
                password=values.pop("password", None),
                host=values.pop("host", None),
                port=int(values.pop("port", 5432)),
                database=values.pop("dbname", None),
            )
            _pool = create_engine(
                url,
                pool_size=3,
                max_overflow=1,
                pool_timeout=10,
                pool_recycle=600,
                pool_pre_ping=True,
                connect_args={
                    **values,
                    "connect_timeout": 10,
                    "options": "-c timezone=UTC -c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000",
                },
            )
        return _pool


def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.dispose()
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

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def convert_row(self, row):
        if row is None:
            return None
        if not isinstance(row, dict):
            row = dict(zip((column.name for column in self.cursor.description), row, strict=True))
        return Row(row)

    def fetchone(self):
        return self.convert_row(self.cursor.fetchone())

    def fetchall(self):
        return [self.convert_row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (self.convert_row(row) for row in self.cursor)


class Connection:
    def __init__(self, connection, session=None):
        self.session = session
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
                    r"ON CONFLICT\s*\(",
                    "ON CONFLICT (project_id,",
                    parts[index],
                    flags=re.IGNORECASE,
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
    from sqlalchemy.orm import Session

    with (
        pool().begin() as transaction,
        Session(bind=transaction, expire_on_commit=False) as session,
    ):
        raw_connection = transaction.connection.driver_connection
        database = Connection(raw_connection, session)
        if ident is None:
            raw_connection.execute("SET LOCAL search_path TO registry, pg_catalog")
        else:
            database.select_project(ident)
        yield database
        session.flush()


def check_schema():
    with connect() as database:
        if database.execute("SELECT version FROM schema_version").fetchone()[0] != 1:
            raise RuntimeError("PostgreSQL schema version is incompatible")
