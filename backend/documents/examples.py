import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .normalization import canonical
from .repository import RecognitionExample, session


def remember(database, owner, rows):
    """Learn confirmed labels only. Never retain document quantities or prices."""
    for row in rows:
        if (
            not row.get("confirmed")
            or row.get("issues")
            or not row.get("section")
            or row["section"] == "Без раздела"
        ):
            continue
        example = {key: row.get(key, "") for key in ("name", "section", "subsection", "unit")}
        identity = json.dumps(
            [owner, *(canonical(value) for value in example.values())], ensure_ascii=False
        )
        ident = hashlib.sha256(identity.encode()).hexdigest()
        insert = postgres_insert if database.bind.dialect.name == "postgresql" else sqlite_insert
        statement = insert(RecognitionExample).values(
            id=ident, owner_id=owner, payload=example, confirmations=1, updated_at=datetime.now(UTC)
        )
        database.execute(
            statement.on_conflict_do_update(
                index_elements=[RecognitionExample.id],
                set_={
                    "payload": statement.excluded.payload,
                    "confirmations": RecognitionExample.confirmations + 1,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )


def confirmed_examples(owner, limit=8):
    with session() as database:
        return list(
            database.scalars(
                select(RecognitionExample.payload)
                .where(RecognitionExample.owner_id == owner)
                .order_by(RecognitionExample.updated_at.desc(), RecognitionExample.id)
                .limit(limit)
            )
        )
