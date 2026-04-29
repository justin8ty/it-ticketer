import json

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import false, or_
from werkzeug.security import check_password_hash

from attachments import save_attachment
from roles_auth import AuthUser, require_role
from db import SessionLocal
from health_check import get_or_create_health_questions, latest_health_check, parse_questions_payload
from models import ClosureConfirmation, HealthCheck, Message, Requester, Status, Technician, Ticket
from notification_service import notify_requester
from tickets import can_close_ticket, list_status_names, set_ticket_lookups, ticket_has_proof
from utils import now_utc


def register_tech_routes(app):
    @app.route("/tech/login", methods=["GET", "POST"])
    def tech_login():
        if request.method == "GET":
            return render_template("tech_login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        db = SessionLocal()
        try:
            t = db.query(Technician).filter(Technician.email == email).first()
            if not t or not t.is_active or not check_password_hash(t.password_hash, password):
                flash("Invalid technician credentials.", "danger")
                return redirect(url_for("tech_login"))

            login_user(AuthUser("tech", t.id, t.email, t.name))
            return redirect(url_for("tech_dashboard"))
        finally:
            db.close()

    @app.get("/tech/logout")
    @login_required
    def tech_logout():
        logout_user()
        return redirect(url_for("index"))

    @app.get("/tech/dashboard")
    @require_role("tech")
    def tech_dashboard():
        status = request.args.get("status", "").strip()
        q = request.args.get("q", "").strip()

        db = SessionLocal()
        try:
            tickets_q = db.query(Ticket).filter(Ticket.assigned_technician_id == current_user.user_id)
            if status:
                status_row = db.query(Status).filter(Status.name == status).first()
                if status_row:
                    tickets_q = tickets_q.filter(Ticket.status_id == status_row.id)
                else:
                    tickets_q = tickets_q.filter(false())
            if q:
                like = f"%{q}%"
                tickets_q = tickets_q.join(Requester)
                tickets_q = tickets_q.filter(
                    or_(Ticket.issue_title.like(like), Requester.email.like(like))
                )

            tickets = tickets_q.order_by(Ticket.updated_at.desc()).all()
            return render_template(
                "tech_dashboard.html",
                tickets=tickets,
                status=status,
                q=q,
                status_options=list_status_names(db),
            )
        finally:
            db.close()

    @app.route("/tech/ticket/<int:ticket_id>", methods=["GET", "POST"])
    @require_role("tech")
    def tech_ticket(ticket_id: int):
        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket or ticket.assigned_technician_id != current_user.user_id:
                abort(404)

            if request.method == "POST":
                action = request.form.get("action")
                requester_notification = None

                if action == "add_message":
                    content = request.form.get("content", "").strip()
                    msg_type = request.form.get("message_type", "Public")
                    if not content:
                        flash("Message cannot be empty.", "danger")
                    else:
                        db.add(
                            Message(
                                ticket_id=ticket.id,
                                technician_id=current_user.user_id,
                                message_type=msg_type,
                                message_text=content,
                            )
                        )
                        ticket.updated_at = now_utc()
                        if msg_type == "Public":
                            requester_notification = (
                                "public_reply",
                                f"New public update from the technician: {content}",
                            )
                        flash("Message posted.", "success")

                elif action == "update_status":
                    previous_status = ticket.status
                    new_status = request.form.get("status", ticket.status).strip()
                    if new_status == "CLOSED":
                        if can_close_ticket(ticket):
                            set_ticket_lookups(ticket, db, status="CLOSED")
                            requester_notification = (
                                "ticket_closed",
                                "Your ticket has been closed after the verification requirements were completed.",
                            )
                            flash("Ticket closed.", "success")
                        else:
                            if not ticket.closure_confirmation or ticket.closure_confirmation.status != "CONFIRMED":
                                set_ticket_lookups(ticket, db, status="PENDING_CONFIRMATION")
                                flash(
                                    "Requester confirmation is required. The ticket status has been changed to PENDING_CONFIRMATION.",
                                    "warning",
                                )
                            else:
                                flash(
                                    "Closure requirements are not satisfied. Upload proof of resolution and record a PASS verification result, or request an administrative override.",
                                    "danger",
                                )
                    else:
                        set_ticket_lookups(ticket, db, status=new_status)
                        if new_status == "REOPENED" and previous_status != "REOPENED":
                            requester_notification = (
                                "ticket_reopened",
                                "Your ticket has been reopened and follow-up work is required.",
                            )
                        flash("Status updated.", "success")

                    ticket.updated_at = now_utc()

                elif action == "upload_attachment":
                    file = request.files.get("file")
                    atype = request.form.get("attachment_type", "Issue")
                    if not file or not file.filename:
                        flash("Please choose a file.", "danger")
                    else:
                        saved = save_attachment(
                            file=file,
                            ticket_id=ticket.id,
                            attachment_type=atype,
                            uploaded_by_role="Technician",
                            uploaded_by_id=current_user.user_id,
                        )
                        if saved:
                            db.add(saved)
                            ticket.updated_at = now_utc()
                            flash(f"Uploaded {atype} file.", "success")
                        else:
                            flash("Upload failed.", "danger")

                elif action == "health_check":
                    raw_questions = request.form.get("questions_json", "")
                    qs = parse_questions_payload(raw_questions)
                    if not qs:
                        qs = get_or_create_health_questions(ticket, db)
                    answers = []
                    missing = False
                    for idx, q in enumerate(qs):
                        a = request.form.get(f"answer_{idx}", "").strip()
                        if not a:
                            missing = True
                        answers.append({"question": q, "answer": a})

                    if missing:
                        flash("Please answer all health verification questions.", "danger")
                    else:
                        result = request.form.get("result", "PASS").strip().upper()
                        if result not in ["PASS", "FAIL"]:
                            result = "PASS"

                        payload = {
                            "category": ticket.category or "Other",
                            "questions": answers,
                        }
                        db.add(
                            HealthCheck(
                                ticket_id=ticket.id,
                                technician_id=current_user.user_id,
                                checklist_json=json.dumps(payload),
                                result=result,
                            )
                        )
                        ticket.updated_at = now_utc()
                        flash("Health check saved.", "success")

                elif action == "request_esign":
                    # Request confirmation only after resolution evidence and verification are complete
                    if not ticket_has_proof(ticket):
                        flash("Upload proof of resolution before requesting confirmation.", "danger")
                    else:
                        hc = latest_health_check(ticket)
                        hc_ok = ticket.closure_override or (hc and hc.result == "PASS")
                        if not hc_ok:
                            flash(
                                "Record a PASS verification result, or request an administrative override, before requesting confirmation.",
                                "danger",
                            )
                        else:
                            cc = ticket.closure_confirmation
                            already_pending = bool(cc and cc.status == "PENDING")
                            if already_pending:
                                flash("Closure confirmation has already been requested.", "warning")
                            else:
                                if not cc:
                                    cc = ClosureConfirmation(ticket_id=ticket.id, requester_id=ticket.requester_id)
                                    db.add(cc)
                                    db.flush()
                                elif cc.status == "CONFIRMED":
                                    cc = ClosureConfirmation(ticket_id=ticket.id, requester_id=ticket.requester_id)
                                    db.add(cc)
                                    db.flush()

                                cc.status = "PENDING"
                                cc.signature_name = None
                                cc.requested_at = now_utc()
                                cc.updated_at = now_utc()

                                set_ticket_lookups(ticket, db, status="PENDING_CONFIRMATION")
                                ticket.updated_at = now_utc()

                                db.add(
                                    Message(
                                        ticket_id=ticket.id,
                                        technician_id=current_user.user_id,
                                        message_type="Public",
                                        message_text="Closure confirmation has been requested. Please sign on the tracking page.",
                                    )
                                )
                                requester_notification = (
                                    "closure_confirmation_requested",
                                    "Closure confirmation is required. Please review the proof-of-fix and sign on the tracking page.",
                                )
                                flash(
                                    "Closure confirmation requested. The requester may sign on the tracking page.",
                                    "success",
                                )

                else:
                    flash("Unsupported action.", "warning")

                db.commit()
                if requester_notification:
                    event_key, summary = requester_notification
                    notify_requester(ticket, event_key, summary, base_url=request.url_root)
                return redirect(url_for("tech_ticket", ticket_id=ticket.id))

            # GET
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            public_msgs = [m for m in ticket.messages if m.message_type == "Public"]
            internal_msgs = [m for m in ticket.messages if m.message_type == "Internal"]
            proof_files = [a for a in ticket.attachments if a.attachment_type == "Proof-of-Fix"]
            issue_files = [a for a in ticket.attachments if a.attachment_type == "Issue"]
            health = latest_health_check(ticket)

            existing_questions_json = ticket.health_questions_json
            qs = get_or_create_health_questions(ticket, db)
            if not existing_questions_json and ticket.health_questions_json:
                try:
                    db.commit()
                except Exception:
                    db.rollback()

            health_questions_json = ticket.health_questions_json or json.dumps(
                qs, ensure_ascii=True, separators=(",", ":")
            )

            return render_template(
                "tech_ticket.html",
                ticket=ticket,
                public_msgs=public_msgs,
                internal_msgs=internal_msgs,
                issue_files=issue_files,
                proof_files=proof_files,
                health=health,
                health_questions=qs,
                health_questions_json=health_questions_json,
                closure=ticket.closure_confirmation,
                status_options=list_status_names(db),
            )
        finally:
            db.close()
