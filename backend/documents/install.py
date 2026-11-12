import os

from sqlalchemy import DDL, Index, func

from .. import postgres
from ..orm_models import Project
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
            Index(
                "projects_owner_name_unique",
                Project.owner_id,
                func.lower(func.trim(Project.name)),
                unique=True,
            ).create(connection, checkfirst=True)
            connection.execute(
                DDL("GRANT SELECT, INSERT, UPDATE, DELETE ON registry.document_jobs TO m100_app")
            )
    finally:
        postgres.close_pool()


if __name__ == "__main__":
    main()
