from collections import Counter
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from roles_auth import AuthUser, require_role
from config import NOTIFICATION_PREFERENCES
from db import SessionLocal
from models import Admin, AdminActionLog, Requester, Status, Technician, Ticket
from notification_service import normalize_notification_preference, notify_requester, notify_technician
from tickets import can_close_ticket, list_category_names, list_priority_names, list_status_names, set_ticket_lookups
from utils import now_utc


def _log_admin_action(db, action: str, target_type: str, target_id: int | None, details: str | None = None) -> None:
    ticket_id = target_id if target_type == "ticket" else None
    db.add(
        AdminActionLog(
            admin_id=current_user.user_id,
            action_type=action,
            ticket_id=ticket_id,
            action_reason=details,
        )
    )


def _build_change_summary(changes: list[str], fallback: str) -> str:
    cleaned = [c.strip() for c in changes if c and c.strip()]
    if not cleaned:
        return fallback
    return "; ".join(cleaned)


def register_admin_routes(app):
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "GET":
            return render_template("admin_login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        db = SessionLocal()
        try:
            a = db.query(Admin).filter(Admin.email == email).first()
            if not a or not a.is_active or not check_password_hash(a.password_hash, password):
                flash("Invalid admin credentials.", "danger")
                return redirect(url_for("admin_login"))

            login_user(AuthUser("admin", a.id, a.email, a.name))
            return redirect(url_for("admin_dashboard"))
        finally:
            db.close()

    @app.get("/admin/logout")
    @login_required
    def admin_logout():
        logout_user()
        return redirect(url_for("index"))

    @app.get("/admin/dashboard")
    @require_role("admin")
    def admin_dashboard():
        db = SessionLocal()
        try:
            tickets = db.query(Ticket).order_by(Ticket.updated_at.desc()).all()
            techs = db.query(Technician).order_by(Technician.skill_group, Technician.name).all()
            status_options = list_status_names(db)
            priority_options = list_priority_names(db)
            category_options = list_category_names(db)

            total = len(tickets)
            closed_status = db.query(Status).filter(Status.name == "CLOSED").first()
            closed_status_id = closed_status.id if closed_status else None
            open_tickets = [t for t in tickets if not closed_status_id or t.status_id != closed_status_id]
            open_count = len(open_tickets)
            closed_count = total - open_count if closed_status_id else 0
            unassigned_tickets = [t for t in open_tickets if not t.assigned_technician_id]
            pending_confirmation_tickets = [t for t in open_tickets if t.status == "PENDING_CONFIRMATION"]
            override_tickets = [t for t in open_tickets if t.closure_override]
            high_priority_tickets = [t for t in open_tickets if (t.priority or "").upper() in {"HIGH", "URGENT"}]
            stale_cutoff = now_utc() - timedelta(days=3)
            stale_tickets = [t for t in open_tickets if t.updated_at and t.updated_at < stale_cutoff]

            status_counts_raw = Counter((t.status or "Unknown") for t in tickets)
            priority_counts_raw = Counter((t.priority or "Unknown") for t in tickets)
            category_counts_raw = Counter((t.category or "Unknown") for t in tickets)

            status_breakdown = [
                {"label": name, "count": status_counts_raw.get(name, 0)} for name in status_options if status_counts_raw.get(name, 0)
            ]
            priority_breakdown = [
                {"label": name, "count": priority_counts_raw.get(name, 0)}
                for name in priority_options
                if priority_counts_raw.get(name, 0)
            ]
            category_breakdown = [
                {"label": name, "count": category_counts_raw.get(name, 0)}
                for name in category_options
                if category_counts_raw.get(name, 0)
            ]
            category_breakdown.sort(key=lambda item: (-item["count"], item["label"]))

            technician_workload = []
            active_technicians = 0
            for tech in techs:
                if tech.is_active:
                    active_technicians += 1
                assigned_open = [t for t in open_tickets if t.assigned_technician_id == tech.id]
                technician_workload.append(
                    {
                        "tech": tech,
                        "open_count": len(assigned_open),
                        "high_priority_count": sum(
                            1 for t in assigned_open if (t.priority or "").upper() in {"HIGH", "URGENT"}
                        ),
                        "pending_confirmation_count": sum(1 for t in assigned_open if t.status == "PENDING_CONFIRMATION"),
                        "latest_update": max((t.updated_at for t in assigned_open), default=None),
                    }
                )
            technician_workload.sort(
                key=lambda item: (-item["open_count"], -item["high_priority_count"], item["tech"].name.lower())
            )

            recent = sorted(tickets, key=lambda t: t.created_at, reverse=True)[:10]
            recent_unassigned = sorted(unassigned_tickets, key=lambda t: t.created_at, reverse=True)[:8]
            recent_high_priority = sorted(high_priority_tickets, key=lambda t: t.updated_at, reverse=True)[:8]
            recent_pending_confirmation = sorted(
                pending_confirmation_tickets, key=lambda t: t.updated_at, reverse=True
            )[:8]
            recent_stale = sorted(stale_tickets, key=lambda t: t.updated_at)[:8]

            return render_template(
                "admin_dashboard.html",
                total=total,
                open_count=open_count,
                closed_count=closed_count,
                active_technicians=active_technicians,
                techs=techs,
                unassigned_count=len(unassigned_tickets),
                pending_confirmation_count=len(pending_confirmation_tickets),
                override_count=len(override_tickets),
                high_priority_count=len(high_priority_tickets),
                stale_count=len(stale_tickets),
                status_breakdown=status_breakdown,
                priority_breakdown=priority_breakdown,
                category_breakdown=category_breakdown,
                technician_workload=technician_workload,
                recent_unassigned=recent_unassigned,
                recent_high_priority=recent_high_priority,
                recent_pending_confirmation=recent_pending_confirmation,
                recent_stale=recent_stale,
                recent=recent,
            )
        finally:
            db.close()

    @app.route("/admin/technicians", methods=["GET", "POST"])
    @require_role("admin")
    def admin_technicians():
        db = SessionLocal()
        try:
            if request.method == "POST":
                action = request.form.get("action")
                if action == "create":
                    email = request.form.get("email", "").strip().lower()
                    name = request.form.get("name", "").strip()
                    skill = request.form.get("skill_group", "General").strip()
                    password = request.form.get("password", "").strip()
                    if not email or not name or not password:
                        flash("Email, name, and password are required.", "danger")
                    else:
                        exists = db.query(Technician).filter(Technician.email == email).first()
                        if exists:
                            flash("Technician email already exists.", "danger")
                        else:
                            technician = Technician(
                                email=email,
                                name=name,
                                password_hash=generate_password_hash(password),
                                skill_group=skill,
                                is_active=True,
                                availability="Available",
                                telegram_chat_id=request.form.get("telegram_chat_id", "").strip() or None,
                                notification_preference=normalize_notification_preference(
                                    request.form.get("notification_preference")
                                ),
                            )
                            db.add(technician)
                            db.flush()
                            _log_admin_action(
                                db,
                                "technician_created",
                                "technician",
                                technician.id,
                                f"Created technician {technician.email}",
                            )
                            db.commit()
                            flash("Technician created.", "success")

            techs = db.query(Technician).order_by(Technician.skill_group, Technician.name).all()
            return render_template(
                "admin_technicians.html",
                techs=techs,
                notification_preferences=NOTIFICATION_PREFERENCES,
            )
        finally:
            db.close()

    @app.route("/admin/technicians/<int:tech_id>/edit", methods=["GET", "POST"])
    @require_role("admin")
    def admin_edit_technician(tech_id: int):
        db = SessionLocal()
        try:
            t = db.query(Technician).filter(Technician.id == tech_id).first()
            if not t:
                abort(404)

            if request.method == "POST":
                email = request.form.get("email", "").strip().lower()
                name = request.form.get("name", "").strip()
                skill = request.form.get("skill_group", "General").strip()
                availability = request.form.get("availability", "Available").strip()
                is_active = request.form.get("is_active") == "on"
                password = request.form.get("password", "").strip()

                if not email or not name:
                    flash("Email and name are required.", "danger")
                    return redirect(url_for("admin_edit_technician", tech_id=tech_id))

                if email != t.email:
                    exists = db.query(Technician).filter(Technician.email == email).first()
                    if exists:
                        flash("Technician email already exists.", "danger")
                        return redirect(url_for("admin_edit_technician", tech_id=tech_id))

                t.email = email
                t.name = name
                t.skill_group = skill
                t.availability = availability
                t.is_active = is_active
                t.telegram_chat_id = request.form.get("telegram_chat_id", "").strip() or None
                t.notification_preference = normalize_notification_preference(
                    request.form.get("notification_preference"),
                    default=t.notification_preference or "BOTH",
                )
                if password:
                    t.password_hash = generate_password_hash(password)
                t.updated_at = now_utc()

                _log_admin_action(
                    db,
                    "technician_updated",
                    "technician",
                    t.id,
                    f"Updated technician {t.email}",
                )
                db.commit()
                flash("Technician updated.", "success")
                return redirect(url_for("admin_technicians"))

            return render_template(
                "admin_technician_edit.html",
                tech=t,
                notification_preferences=NOTIFICATION_PREFERENCES,
            )
        finally:
            db.close()

    @app.post("/admin/technicians/<int:tech_id>/toggle")
    @require_role("admin")
    def admin_toggle_technician(tech_id: int):
        db = SessionLocal()
        try:
            t = db.query(Technician).filter(Technician.id == tech_id).first()
            if not t:
                abort(404)
            t.is_active = not t.is_active
            t.updated_at = now_utc()
            _log_admin_action(
                db,
                "technician_toggled",
                "technician",
                t.id,
                f"Set technician active={t.is_active}",
            )
            db.commit()
            flash("Technician status updated.", "success")
            return redirect(url_for("admin_technicians"))
        finally:
            db.close()

    @app.route("/admin/ticket/<int:ticket_id>/edit", methods=["GET", "POST"])
    @require_role("admin")
    def admin_edit_ticket(ticket_id: int):
        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                abort(404)
            techs = db.query(Technician).order_by(Technician.skill_group, Technician.name).all()
            categories = list_category_names(db)
            priorities = list_priority_names(db)
            status_options = list_status_names(db)

            if request.method == "POST":
                previous_state = {
                    "issue_title": ticket.issue_title,
                    "description": ticket.description,
                    "category": ticket.category,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "assigned_technician_id": ticket.assigned_technician_id,
                }
                requester_name = request.form.get("requester_name", "").strip()
                requester_email = request.form.get("requester_email", "").strip()
                requester_phone = request.form.get("requester_phone", "").strip() or None
                requester_telegram_chat_id = request.form.get("requester_telegram_chat_id", "").strip() or None
                requester_notification_preference = normalize_notification_preference(
                    request.form.get("requester_notification_preference"),
                    default=ticket.requester_notification_preference or "BOTH",
                )
                issue_title = request.form.get("issue_title", "").strip()
                description = request.form.get("description", "").strip()
                category = request.form.get("category", ticket.category).strip()
                priority = request.form.get("priority", ticket.priority).strip()
                status = request.form.get("status", ticket.status).strip()
                tech_id = request.form.get("assigned_technician_id", "").strip()

                if not requester_name or not requester_email or not issue_title or not description:
                    flash("Requester name, email, title, and description are required.", "danger")
                    return redirect(url_for("admin_edit_ticket", ticket_id=ticket_id))

                if category not in categories:
                    category = "Other"
                if priority not in priorities:
                    priority = "Medium"
                if status not in status_options:
                    status = ticket.status

                assigned_id = None
                if tech_id:
                    try:
                        assigned_id = int(tech_id)
                    except ValueError:
                        assigned_id = None

                if not ticket.requester:
                    ticket.requester = Requester(
                        name=requester_name,
                        email=requester_email,
                        phone=requester_phone,
                        telegram_chat_id=requester_telegram_chat_id,
                        notification_preference=requester_notification_preference,
                    )
                else:
                    ticket.requester.name = requester_name
                    ticket.requester.email = requester_email
                    ticket.requester.phone = requester_phone
                    ticket.requester.telegram_chat_id = requester_telegram_chat_id
                    ticket.requester.notification_preference = requester_notification_preference
                    ticket.requester.updated_at = now_utc()
                ticket.issue_title = issue_title
                ticket.description = description
                ticket.assigned_technician_id = assigned_id
                set_ticket_lookups(ticket, db, category=category, priority=priority)
                ticket.updated_at = now_utc()

                if status == "CLOSED" and not can_close_ticket(ticket):
                    if not ticket.closure_confirmation or ticket.closure_confirmation.status != "CONFIRMED":
                        set_ticket_lookups(ticket, db, status="PENDING_CONFIRMATION")
                        flash(
                            "Requester confirmation is still required. Status changed to PENDING_CONFIRMATION instead of CLOSED.",
                            "warning",
                        )
                    else:
                        set_ticket_lookups(ticket, db, status=previous_state["status"])
                        flash(
                            "Closure requirements are not satisfied. The ticket remains at its previous status.",
                            "danger",
                        )
                else:
                    set_ticket_lookups(ticket, db, status=status)
                    flash("Ticket updated.", "success")

                significant_changes = []
                if previous_state["assigned_technician_id"] != ticket.assigned_technician_id:
                    assigned_technician = next(
                        (tech for tech in techs if tech.id == ticket.assigned_technician_id), None
                    )
                    if assigned_technician:
                        significant_changes.append(f"Assigned technician: {assigned_technician.name}")
                    else:
                        significant_changes.append("Assigned technician: Unassigned")
                if previous_state["status"] != ticket.status:
                    significant_changes.append(f"Status: {previous_state['status']} -> {ticket.status}")
                if previous_state["priority"] != ticket.priority:
                    significant_changes.append(f"Priority: {previous_state['priority']} -> {ticket.priority}")
                if previous_state["category"] != ticket.category:
                    significant_changes.append(f"Category: {previous_state['category']} -> {ticket.category}")
                if previous_state["issue_title"] != ticket.issue_title:
                    significant_changes.append("Issue title updated")
                if previous_state["description"] != ticket.description:
                    significant_changes.append("Description updated")

                _log_admin_action(
                    db,
                    "ticket_updated",
                    "ticket",
                    ticket.id,
                    _build_change_summary(significant_changes, "Admin updated ticket details."),
                )
                db.commit()

                assigned_technician = next((tech for tech in techs if tech.id == ticket.assigned_technician_id), None)
                if assigned_technician and significant_changes:
                    tech_event = (
                        "ticket_assigned"
                        if previous_state["assigned_technician_id"] != ticket.assigned_technician_id
                        else "ticket_updated"
                    )
                    notify_technician(
                        ticket,
                        tech_event,
                        _build_change_summary(significant_changes, "Admin updated ticket details."),
                        base_url=request.url_root,
                        technician=assigned_technician,
                    )

                if previous_state["status"] != ticket.status and ticket.status == "CLOSED":
                    notify_requester(
                        ticket,
                        "ticket_closed",
                        "Your ticket has been closed.",
                        base_url=request.url_root,
                    )
                elif previous_state["status"] != ticket.status and ticket.status == "REOPENED":
                    notify_requester(
                        ticket,
                        "ticket_reopened",
                        "Your ticket has been reopened and follow-up work is required.",
                        base_url=request.url_root,
                    )
                return redirect(url_for("admin_dashboard"))

            return render_template(
                "admin_ticket_edit.html",
                ticket=ticket,
                techs=techs,
                categories=categories,
                notification_preferences=NOTIFICATION_PREFERENCES,
                priorities=priorities,
                status_options=status_options,
            )
        finally:
            db.close()

    @app.post("/admin/ticket/<int:ticket_id>/override")
    @require_role("admin")
    def admin_override(ticket_id: int):
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Override reason is required.", "danger")
            return redirect(url_for("admin_dashboard"))

        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                abort(404)
            ticket.closure_override = True
            ticket.override_reason = reason
            ticket.override_by_admin_id = current_user.user_id
            ticket.updated_at = now_utc()
            _log_admin_action(
                db,
                "closure_override_enabled",
                "ticket",
                ticket.id,
                reason,
            )
            db.commit()
            notify_technician(
                ticket,
                "ticket_updated",
                f"Admin recorded a supervisor override for closure verification. Reason: {reason}",
                base_url=request.url_root,
            )
            flash("Override applied.", "success")
            return redirect(url_for("admin_dashboard"))
        finally:
            db.close()
