import os
from datetime import UTC, datetime

from sqlalchemy import DDL, Index, func, select
from sqlalchemy.orm import Session

from .. import postgres
from ..naming import normalize_existing_project_names
from ..orm_models import AuditEvent, Project
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
            with Session(bind=connection) as database:
                projects = list(
                    database.scalars(
                        select(Project).order_by(Project.created_at, Project.id).with_for_update()
                    )
                )
                for project, before in normalize_existing_project_names(projects):
                    now = datetime.now(UTC)
                    database.add(
                        AuditEvent(
                            project_id=project.id,
                            date=now.date(),
                            created_at=now,
                            payload={
                                "action": "project_name_normalized",
                                "actor_name": "Система",
                                "position_name": before + " → " + project.name,
                                "before_name": before,
                                "after_name": project.name,
                            },
                        )
                    )
                database.flush()
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
