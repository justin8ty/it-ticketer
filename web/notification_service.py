import logging
import smtplib
from email.message import EmailMessage

import requests

from config import (
    APP_BASE_URL,
    NOTIFY_EMAIL_ENABLED,
    NOTIFY_TELEGRAM_ENABLED,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    TELEGRAM_BOT_TOKEN,
)

logger = logging.getLogger(__name__)

VALID_NOTIFICATION_PREFERENCES = {"BOTH", "EMAIL", "TELEGRAM", "NONE"}

TECHNICIAN_EVENT_TITLES = {
    "ticket_assigned": "New Ticket Assigned",
    "ticket_updated": "Ticket Updated",
    "ticket_closed": "Ticket Closed",
    "ticket_reopened": "Ticket Reopened / Follow-up Required",
}

REQUESTER_EVENT_TITLES = {
    "ticket_created": "Ticket Submitted",
    "public_reply": "New Ticket Update",
    "closure_confirmation_requested": "Closure Confirmation Required",
    "ticket_closed": "Ticket Closed",
    "ticket_reopened": "Ticket Reopened / Follow-up Required",
}


def normalize_notification_preference(value: str | None, default: str = "BOTH") -> str:
    pref = (value or default).strip().upper()
    if pref not in VALID_NOTIFICATION_PREFERENCES:
        return default
    return pref


def send_email_notification(recipient_email: str, subject: str, body: str) -> bool:
    if not NOTIFY_EMAIL_ENABLED:
        logger.info("Email notifications disabled; skipping email delivery to %s", recipient_email)
        return False
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("Email notification config incomplete; skipping email delivery to %s", recipient_email)
        return False
    if not recipient_email:
        logger.info("Email recipient missing; skipping email notification")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = recipient_email
    msg.set_content(body)

    try:
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                if SMTP_USE_TLS:
                    server.starttls()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        logger.info("Email notification sent to %s", recipient_email)
        return True
    except Exception:
        logger.exception("Email notification failed for %s", recipient_email)
        return False


def send_telegram_notification(chat_id: str, message: str) -> bool:
    if not NOTIFY_TELEGRAM_ENABLED:
        logger.info("Telegram notifications disabled; skipping Telegram delivery to %s", chat_id)
        return False
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram bot token missing; skipping Telegram delivery to %s", chat_id)
        return False
    if not chat_id:
        logger.info("Telegram chat ID missing; skipping Telegram notification")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(payload.get("description") or "Unknown Telegram API error")
        logger.info("Telegram notification sent to chat_id=%s", chat_id)
        return True
    except Exception:
        logger.exception("Telegram notification failed for chat_id=%s", chat_id)
        return False


def _channel_allowed(preference: str, channel: str) -> bool:
    if preference == "NONE":
        return False
    if preference == "BOTH":
        return True
    return preference == channel


def _summarize(text: str | None, limit: int = 220) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "No additional details were provided."
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _resolve_base_url(base_url: str | None) -> str:
    return (APP_BASE_URL or base_url or "").rstrip("/")


def _build_message(audience: str, event_title: str, ticket, summary: str, base_url: str | None) -> tuple[str, str]:
    resolved_base_url = _resolve_base_url(base_url)
    subject = f"[Ticket #{ticket.id}] {event_title}"
    lines = [
        event_title,
        "",
        f"Ticket ID: {ticket.id}",
        f"Issue Title: {ticket.issue_title}",
        f"Current Status: {ticket.status}",
        f"Update Summary: {_summarize(summary)}",
    ]

    if audience == "requester" and resolved_base_url:
        lines.append(f"Tracking Link: {resolved_base_url}/t/{ticket.tracking_token}")
    if audience == "technician" and resolved_base_url:
        lines.append(f"Dashboard Link: {resolved_base_url}/tech/ticket/{ticket.id}")

    return subject, "\n".join(lines)


def _dispatch_notification(
    *,
    recipient_label: str,
    email: str | None,
    telegram_chat_id: str | None,
    preference: str | None,
    subject: str,
    body: str,
    ticket_id: int,
    event_key: str,
) -> bool:
    normalized_preference = normalize_notification_preference(preference)
    attempted = False
    delivered = False

    if _channel_allowed(normalized_preference, "EMAIL") and email:
        attempted = True
        delivered = send_email_notification(email, subject, body) or delivered

    if _channel_allowed(normalized_preference, "TELEGRAM") and telegram_chat_id:
        attempted = True
        delivered = send_telegram_notification(telegram_chat_id, body) or delivered

    if not attempted:
        logger.info(
            "No notification channels available for %s on ticket #%s event=%s",
            recipient_label,
            ticket_id,
            event_key,
        )
        return False

    if delivered:
        logger.info("Notification delivered for %s on ticket #%s event=%s", recipient_label, ticket_id, event_key)
    else:
        logger.warning("Notification delivery failed for %s on ticket #%s event=%s", recipient_label, ticket_id, event_key)
    return delivered


def notify_technician(ticket, event_key: str, summary: str, base_url: str | None = None, technician=None) -> bool:
    tech = technician or getattr(ticket, "assigned_technician", None)
    if not tech:
        logger.info("No assigned technician available for ticket #%s event=%s", ticket.id, event_key)
        return False

    event_title = TECHNICIAN_EVENT_TITLES.get(event_key, "Ticket Update")
    subject, body = _build_message("technician", event_title, ticket, summary, base_url)
    return _dispatch_notification(
        recipient_label=f"technician:{tech.id}",
        email=getattr(tech, "email", None),
        telegram_chat_id=getattr(tech, "telegram_chat_id", None),
        preference=getattr(tech, "notification_preference", None),
        subject=subject,
        body=body,
        ticket_id=ticket.id,
        event_key=event_key,
    )


def notify_requester(ticket, event_key: str, summary: str, base_url: str | None = None) -> bool:
    event_title = REQUESTER_EVENT_TITLES.get(event_key, "Ticket Update")
    subject, body = _build_message("requester", event_title, ticket, summary, base_url)
    return _dispatch_notification(
        recipient_label=f"requester:{ticket.requester_email}",
        email=getattr(ticket, "requester_email", None),
        telegram_chat_id=getattr(ticket, "requester_telegram_chat_id", None),
        preference=getattr(ticket, "requester_notification_preference", None),
        subject=subject,
        body=body,
        ticket_id=ticket.id,
        event_key=event_key,
    )
