import json
import secrets
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, send_from_directory, url_for

from ai_triage import triage_with_gemini
from attachments import save_attachment
from db import SessionLocal
from health_check import format_health_check_display, health_questions, latest_health_check
from models import Attachment, ClosureConfirmation, Message, Requester, Ticket
from notification_service import normalize_notification_preference, notify_requester, notify_technician
from tickets import can_close_ticket, list_category_names, pick_technician, set_ticket_lookups
from utils import now_utc, save_signature_image


def register_public_routes(app):
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/submit", methods=["GET", "POST"])
    def submit():
        if request.method == "GET":
            db = SessionLocal()
            try:
                return render_template("submit.html", categories=list_category_names(db))
            finally:
                db.close()

        requester_name = request.form.get("requester_name", "").strip()
        requester_email = request.form.get("requester_email", "").strip()
        requester_phone = request.form.get("requester_phone", "").strip() or None
        requester_telegram_chat_id = request.form.get("requester_telegram_chat_id", "").strip() or None
        requester_notification_preference = normalize_notification_preference(
            request.form.get("requester_notification_preference")
        )
        issue_title = request.form.get("issue_title", "").strip()
        description = request.form.get("description", "").strip()

        if not requester_name or not requester_email or not issue_title or not description:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("submit"))

        token = secrets.token_urlsafe(16)

        triage = triage_with_gemini(issue_title, description)
        category = triage.get("category", "Other")
        priority = triage.get("priority", "Medium")
        skill_group = triage.get("skill_group", "General")
        health_qs = health_questions(issue_title, description, category)
        health_questions_json = json.dumps(health_qs, ensure_ascii=True, separators=(",", ":"))

        db = SessionLocal()
        try:
            tech = pick_technician(db, skill_group)
            requester_row = Requester(
                name=requester_name,
                email=requester_email,
                phone=requester_phone,
                telegram_chat_id=requester_telegram_chat_id,
                notification_preference=requester_notification_preference,
                updated_at=now_utc(),
            )
            db.add(requester_row)
            db.flush()

            ticket = Ticket(
                tracking_token=token,
                requester_id=requester_row.id,
                issue_title=issue_title,
                description=description,
                assigned_technician_id=tech.id if tech else None,
                ai_summary=triage.get("summary"),
                ai_solution_suggestion=triage.get("solution"),
                ai_suggested_skill_group=skill_group,
                ai_model=triage.get("_model"),
                ai_raw_json=triage.get("_raw"),
                health_questions_json=health_questions_json,
                updated_at=now_utc(),
            )
            set_ticket_lookups(ticket, db, category=category, priority=priority, status="NEW")
            db.add(ticket)
            db.flush()

            file = request.files.get("attachment")
            if file and file.filename:
                saved = save_attachment(
                    file=file,
                    ticket_id=ticket.id,
                    attachment_type="Issue",
                    uploaded_by_role="Requester",
                    uploaded_by_id=requester_row.id,
                )
                if saved:
                    db.add(saved)

            # Create closure confirmation row
            db.add(
                ClosureConfirmation(
                    ticket_id=ticket.id,
                    requester_id=requester_row.id,
                    confirmation_status="NOT_REQUESTED",
                )
            )

            db.commit()
            notify_requester(
                ticket,
                "ticket_created",
                "Your ticket has been submitted successfully. Use the tracking link to follow status updates.",
                base_url=request.url_root,
            )
            if tech:
                notify_technician(
                    ticket,
                    "ticket_assigned",
                    "A new ticket has been created and assigned to you.",
                    base_url=request.url_root,
                    technician=tech,
                )
            return redirect(url_for("submitted", token=token))
        finally:
            db.close()

    @app.get("/submitted/<token>")
    def submitted(token: str):
        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.tracking_token == token).first()
            if not ticket:
                abort(404)
            return render_template("submitted.html", ticket=ticket)
        finally:
            db.close()

    @app.route("/t/<token>", methods=["GET", "POST"])
    def track(token: str):
        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.tracking_token == token).first()
            if not ticket:
                abort(404)

            if request.method == "POST":
                action = request.form.get("action")
                if action == "confirm_esign":
                    signature_data = (request.form.get("signature_data", "") or "").strip()
                    cc = ticket.closure_confirmation
                    if not cc or cc.status != "PENDING":
                        flash("No closure confirmation is pending for this ticket.", "warning")
                        return redirect(url_for("track", token=token))

                    signature_file = save_signature_image(signature_data, ticket.id)
                    if not signature_file:
                        flash("Please provide a signature before submitting confirmation.", "danger")
                        return redirect(url_for("track", token=token))

                    cc.status = "CONFIRMED"
                    cc.signature_name = signature_file
                    cc.confirmed_at = now_utc()
                    cc.updated_at = now_utc()
                    ticket.updated_at = now_utc()
                    db.add(
                        Message(
                            ticket_id=ticket.id,
                            requester_id=ticket.requester_id,
                            message_type="Public",
                            message_text="Requester confirmed closure by electronic signature.",
                        )
                    )

                    ticket_closed = False
                    if ticket.status == "PENDING_CONFIRMATION" and can_close_ticket(ticket):
                        set_ticket_lookups(ticket, db, status="CLOSED")
                        ticket_closed = True

                    db.commit()
                    if ticket_closed:
                        notify_requester(
                            ticket,
                            "ticket_closed",
                            "Closure confirmation was received and the ticket is now closed.",
                            base_url=request.url_root,
                        )
                        notify_technician(
                            ticket,
                            "ticket_closed",
                            "The requester confirmed closure and the ticket is now closed.",
                            base_url=request.url_root,
                        )
                    flash("Your confirmation has been recorded.", "success")
                    return redirect(url_for("track", token=token))

                flash("Unsupported action.", "warning")
                return redirect(url_for("track", token=token))

            public_msgs = [m for m in ticket.messages if m.message_type == "Public"]
            proof_files = [a for a in ticket.attachments if a.attachment_type == "Proof-of-Fix"]
            issue_files = [a for a in ticket.attachments if a.attachment_type == "Issue"]
            health = latest_health_check(ticket)
            health_display = format_health_check_display(health)

            return render_template(
                "track.html",
                ticket=ticket,
                public_msgs=public_msgs,
                issue_files=issue_files,
                proof_files=proof_files,
                health=health,
                health_display=health_display,
                closure=ticket.closure_confirmation,
            )
        finally:
            db.close()

    @app.get("/download/<int:attachment_id>")
    def download_attachment(attachment_id: int):
        db = SessionLocal()
        try:
            att = db.query(Attachment).filter(Attachment.id == attachment_id).first()
            if not att:
                abort(404)
            path = Path(att.path)
            if not path.exists():
                abort(404)
            return send_from_directory(path.parent, path.name, as_attachment=True)
        finally:
            db.close()
