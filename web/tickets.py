from typing import Type

from werkzeug.security import generate_password_hash

from config import CATEGORIES, PRIORITIES, STATUSES
from db import SessionLocal
from health_check import latest_health_check
from models import Admin, Category, Priority, Status, Technician, Ticket


LookupModel = Type[Category] | Type[Priority] | Type[Status]


def _seed_lookup(db, model: LookupModel, names: list[str]) -> None:
    existing = {row.name for row in db.query(model).all()}
    for sort_order, name in enumerate(names, start=1):
        if name in existing:
            row = db.query(model).filter(model.name == name).first()
            if row and row.sort_order != sort_order:
                row.sort_order = sort_order
            continue
        db.add(model(name=name, sort_order=sort_order))


def get_lookup(db, model: LookupModel, name: str | None, default: str):
    resolved = (name or default).strip() or default
    row = db.query(model).filter(model.name == resolved).first()
    if row:
        return row

    if resolved != default:
        row = db.query(model).filter(model.name == default).first()
        if row:
            return row

    row = model(name=default, sort_order=999)
    db.add(row)
    db.flush()
    return row


def get_lookup_id(db, model: LookupModel, name: str | None, default: str) -> int:
    return get_lookup(db, model, name, default).id


def set_ticket_lookups(
    ticket: Ticket,
    db,
    *,
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
) -> None:
    if category is not None:
        row = get_lookup(db, Category, category, "Other")
        ticket.category_ref = row
        ticket.category_id = row.id
    if priority is not None:
        row = get_lookup(db, Priority, priority, "Medium")
        ticket.priority_ref = row
        ticket.priority_id = row.id
    if status is not None:
        row = get_lookup(db, Status, status, "NEW")
        ticket.status_ref = row
        ticket.status_id = row.id


def list_lookup_names(db, model: LookupModel) -> list[str]:
    return [row.name for row in db.query(model).order_by(model.sort_order.asc(), model.name.asc()).all()]


def list_category_names(db) -> list[str]:
    values = list_lookup_names(db, Category)
    return values or CATEGORIES


def list_priority_names(db) -> list[str]:
    values = list_lookup_names(db, Priority)
    return values or PRIORITIES


def list_status_names(db) -> list[str]:
    values = list_lookup_names(db, Status)
    return values or STATUSES


def pick_technician(db, skill_group: str) -> Technician | None:
    q = db.query(Technician).filter(Technician.is_active == True)
    tech = (
        q.filter(Technician.skill_group == skill_group)
        .filter(Technician.availability != "Off")
        .order_by(Technician.id.asc())
        .first()
    )
    if tech:
        return tech
    return q.filter(Technician.availability != "Off").order_by(Technician.id.asc()).first()


def ensure_seed_data() -> None:
    db = SessionLocal()
    try:
        _seed_lookup(db, Category, CATEGORIES)
        _seed_lookup(db, Priority, PRIORITIES)
        _seed_lookup(db, Status, STATUSES)

        if db.query(Admin).count() == 0:
            db.add(
                Admin(
                    email="admin@demo.local",
                    name="Demo Admin",
                    password_hash=generate_password_hash("admin123"),
                    is_active=True,
                )
            )

        if db.query(Technician).count() == 0:
            techs = [
                ("net@demo.local", "Network Tech", "Network"),
                ("hw@demo.local", "Hardware Tech", "Hardware"),
                ("sw@demo.local", "Software Tech", "Software"),
                ("print@demo.local", "Printer Tech", "Printer"),
            ]
            for email, name, skill in techs:
                db.add(
                    Technician(
                        email=email,
                        name=name,
                        password_hash=generate_password_hash("tech123"),
                        skill_group=skill,
                        is_active=True,
                        availability="Available",
                    )
                )
        db.commit()
    finally:
        db.close()


def ticket_has_proof(ticket: Ticket) -> bool:
    return any(a.attachment_type == "Proof-of-Fix" for a in ticket.attachments)


def is_requester_confirmed(ticket: Ticket) -> bool:
    cc = ticket.closure_confirmation
    return bool(cc and cc.status == "CONFIRMED")


def can_close_ticket(ticket: Ticket) -> bool:
    if not ticket_has_proof(ticket):
        return False
    if not is_requester_confirmed(ticket):
        return False
    if ticket.closure_override:
        return True
    hc = latest_health_check(ticket)
    return bool(hc and hc.result == "PASS")
