import os

from sqlalchemy import DDL

from .. import postgres
from .repository import DocumentJob


def main():
    owner = os.getenv("POSTGRES_OWNER_URL")
    if not owner:
        raise SystemExit(
            "Set POSTGRES_OWNER_URL for the schema owner. Runtime credentials must remain restricted."
        )
    os.environ["DATABASE_URL"] = owner
    try:
        with postgres.pool().begin() as connection:
            DocumentJob.__table__.create(connection, checkfirst=True)
            connection.execute(
                DDL("GRANT SELECT, INSERT, UPDATE, DELETE ON registry.document_jobs TO m100_app")
            )
    finally:
        postgres.close_pool()


if __name__ == "__main__":
    main()
