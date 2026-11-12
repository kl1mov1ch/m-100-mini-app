from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .orm_models import Entry, Position, ProjectSetting, Report


def positions(database):
    totals = (
        select(Entry.item_id, func.sum(Entry.quantity).label("quantity"))
        .where(Entry.project_id == database.project)
        .group_by(Entry.item_id)
        .subquery()
    )
    completed = Position.baseline + func.coalesce(totals.c.quantity, 0)
    statement = (
        select(Position, func.round(completed, 4), func.round(Position.planned - completed, 4))
        .outerjoin(totals, totals.c.item_id == Position.id)
        .where(Position.project_id == database.project)
        .order_by(Position.source_row)
    )
    result = []
    for position, done, remaining in database.session.execute(statement):
        values = {
            column.name: getattr(position, column.name) for column in Position.__table__.columns
        }
        for field in ("planned", "rate", "baseline"):
            values[field] = float(values[field])
        values.update(completed=float(done), remaining=float(remaining))
        result.append(values)
    return result


def insert_position(database, values):
    fields = ("id", "name", "section", "unit", "planned", "rate", "source_row")
    item = Position(
        project_id=database.project,
        **{field: values[field] for field in fields},
        source_sheet=values.get("source_sheet", ""),
        baseline=values.get("baseline", 0),
    )
    database.session.add(item)
    database.session.flush()


def setting(database, key, default=""):
    if not hasattr(database, "settings_cache"):
        database.settings_cache = {}
    if database.project not in database.settings_cache:
        database.settings_cache[database.project] = dict(
            database.session.execute(
                select(ProjectSetting.key, ProjectSetting.value).where(
                    ProjectSetting.project_id == database.project
                )
            ).all()
        )
    return database.settings_cache[database.project].get(key, default)


def set_setting(database, key, value):
    statement = insert(ProjectSetting).values(project_id=database.project, key=key, value=value)
    database.session.execute(
        statement.on_conflict_do_update(
            index_elements=[ProjectSetting.project_id, ProjectSetting.key],
            set_={"value": statement.excluded.value},
        )
    )
    if hasattr(database, "settings_cache") and database.project in database.settings_cache:
        database.settings_cache[database.project][key] = value
    database.session.expire_all()


def report_history(database):
    reports = {
        row.date: row
        for row in database.session.scalars(
            select(Report).where(Report.project_id == database.project)
        )
    }
    totals = defaultdict(Decimal)
    counts = defaultdict(int)
    statement = (
        select(Entry.date, Entry.quantity, Position.rate)
        .join(Position, (Position.id == Entry.item_id) & (Position.project_id == Entry.project_id))
        .where(Entry.project_id == database.project)
    )
    for day, quantity, rate in database.session.execute(statement):
        totals[day] += quantity * rate
        counts[day] += 1
    result = []
    for day in sorted(set(reports) | set(totals), reverse=True):
        report = reports.get(day)
        amount = totals[day].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        crew = report.crew_count if report else 1
        cents = int(amount * 100)
        base, extra = divmod(cents, crew)
        result.append(
            {
                "date": day.isoformat(),
                "positions": counts[day],
                "amount": float(amount),
                "crew_count": crew if report and report.revision else None,
                "per_person": base / 100,
                "extra_people": extra,
                "extra_per_person": (base + 1) / 100,
                "currency": "BYN",
                "revision": report.revision if report else 0,
                "sync_status": report.sync_status if report else "imported",
                "sync_error": report.sync_error if report else "",
                "updated_at": report.updated_at.isoformat()
                if report and report.updated_at
                else None,
            }
        )
    return result
