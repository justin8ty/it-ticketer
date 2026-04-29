import json
import logging

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL, HEALTH_AI_ENABLED, HEALTH_AI_QUESTION_COUNT
from models import HealthCheck, Ticket

logger = logging.getLogger(__name__)

HEALTH_CHECK_FALLBACK = {
    "Network": [
        "Is the device getting a valid IP address (DHCP or static)?",
        "Can you ping the default gateway from the device?",
        "Is DNS resolving common hostnames correctly?",
        "Is the connection stable (cable / WiFi signal)?",
        "Any recent network changes or outages reported?",
    ],
    "Hardware": [
        "Is the device powered on and hardware indicators normal?",
        "Any errors in device logs (disk, memory, hardware)?",
        "Is available disk space above 20 percent?",
        "CPU and memory usage within normal range?",
        "Peripherals working correctly (monitor, keyboard, mouse)?",
    ],
    "Software": [
        "Is the issue resolved after restarting the application?",
        "Is the application version up to date?",
        "Any relevant error messages captured (screenshots/logs)?",
        "Required background services are running?",
        "Any recent updates/installs that could be related?",
    ],
    "Printer": [
        "Is the printer online and reachable from the device?",
        "Correct drivers installed and selected?",
        "Any paper/toner alerts on the printer panel?",
        "Can a test page print successfully?",
        "Print queue is not stuck/paused?",
    ],
    "Account": [
        "Can the user authenticate from another device?",
        "Account is not locked and password not expired?",
        "Required permissions/groups are correctly set?",
        "MFA/SSO services working normally?",
        "Any recent account changes that could affect access?",
    ],
    "Other": [
        "What exact symptom/error is observed now?",
        "What steps reproduce the issue (if any)?",
        "Device/environment details confirmed (model, OS, location)?",
        "Was a restart performed? What was the result?",
        "Any recent changes that could be related?",
    ],
}


def latest_health_check(ticket: Ticket) -> HealthCheck | None:
    if not ticket.health_checks:
        return None
    return sorted(ticket.health_checks, key=lambda x: x.created_at)[-1]


def _extract_json_text(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    if cleaned.startswith("{") or cleaned.startswith("["):
        return cleaned
    start_obj = cleaned.find("{")
    start_arr = cleaned.find("[")
    starts = [s for s in [start_obj, start_arr] if s != -1]
    if not starts:
        return cleaned
    start = min(starts)
    end_obj = cleaned.rfind("}")
    end_arr = cleaned.rfind("]")
    end = max(end_obj, end_arr)
    if end > start:
        return cleaned[start:end + 1]
    return cleaned


def _sanitize_questions(raw_questions: list[str], fallback_category: str, max_questions: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for q in raw_questions:
        if q is None:
            continue
        q_text = str(q).replace("\n", " ").strip()
        if not q_text:
            continue
        if len(q_text) > 180:
            q_text = q_text[:180].rstrip()
        if not q_text.endswith("?"):
            q_text = q_text.rstrip(".")
            q_text = f"{q_text}?"
        key = q_text.lower()
        if key in seen:
            continue
        cleaned.append(q_text)
        seen.add(key)
        if len(cleaned) >= max_questions:
            break

    if len(cleaned) < max_questions:
        for q in HEALTH_CHECK_FALLBACK.get(fallback_category, HEALTH_CHECK_FALLBACK["Other"]):
            q_text = str(q).strip()
            if not q_text:
                continue
            key = q_text.lower()
            if key in seen:
                continue
            cleaned.append(q_text)
            seen.add(key)
            if len(cleaned) >= max_questions:
                break

    if not cleaned:
        return HEALTH_CHECK_FALLBACK.get(fallback_category, HEALTH_CHECK_FALLBACK["Other"])
    return cleaned


def _health_questions_ai(issue_title: str, description: str, category: str, max_questions: int) -> list[str] | None:
    if not GEMINI_API_KEY or not HEALTH_AI_ENABLED:
        return None

    prompt = f"""
You are an IT helpdesk quality-assurance assistant.

Return ONLY valid JSON (no markdown) with EXACT key:
questions

Rules:
- questions must be concise, actionable checks for a technician who just fixed the issue
- avoid asking for credentials or personal data
- tailor to the specific issue details; avoid generic category-only questions
- include at least 2 questions that reference the reported issue or reproduction steps
- provide exactly {max_questions} questions

Category: {category}
Title: {issue_title}
Description: {description}
""".strip()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    try:
        resp = requests.post(
            url,
            params={"key": GEMINI_API_KEY},
            timeout=30,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = _extract_json_text(text)
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "questions" in parsed:
            parsed = parsed.get("questions", [])
        if not isinstance(parsed, list):
            return None
        return [str(q).strip() for q in parsed if str(q).strip()]
    except Exception:
        logger.exception("Gemini health-check generation failed; falling back.")
        return None


def parse_questions_payload(raw_json: str) -> list[str] | None:
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except Exception:
        return None
    if isinstance(data, dict) and "questions" in data:
        data = data.get("questions", [])
    if not isinstance(data, list):
        return None
    questions = []
    for q in data:
        q_text = str(q).strip()
        if q_text:
            questions.append(q_text)
    return questions or None


def _issue_specific_questions(issue_title: str, description: str) -> list[str]:
    title = (issue_title or "").strip()
    if not title:
        title = "the reported issue"
    short_title = title if len(title) <= 80 else title[:80].rstrip()
    return [
        f"Can you reproduce '{short_title}' after applying the fix?",
        f"What exact steps did you use to verify '{short_title}' is resolved?",
        "Are there any remaining errors, alerts, or symptoms related to this issue?",
        "Did the fix introduce any side effects in related apps, services, or devices?",
    ]


def health_questions(issue_title: str, description: str, category: str) -> list[str]:
    fallback_category = category if category in HEALTH_CHECK_FALLBACK else "Other"
    max_questions = HEALTH_AI_QUESTION_COUNT
    ai_questions = _health_questions_ai(issue_title, description, fallback_category, max_questions)
    if ai_questions:
        return _sanitize_questions(ai_questions, fallback_category, max_questions)
    fallback = _issue_specific_questions(issue_title, description) + HEALTH_CHECK_FALLBACK.get(
        fallback_category, HEALTH_CHECK_FALLBACK["Other"]
    )
    return _sanitize_questions(fallback, fallback_category, max_questions)


def get_or_create_health_questions(ticket: Ticket, db=None) -> list[str]:
    existing = parse_questions_payload(ticket.health_questions_json or "")
    if existing:
        return existing
    qs = health_questions(ticket.issue_title, ticket.description, ticket.category)
    ticket.health_questions_json = json.dumps(qs, ensure_ascii=True, separators=(",", ":"))
    if db is not None:
        db.add(ticket)
    return qs


def format_health_check_display(health: HealthCheck | None) -> dict | None:
    if not health or not health.checklist_json:
        return None
    try:
        data = json.loads(health.checklist_json)
    except Exception:
        return {"type": "raw", "raw": health.checklist_json}

    if isinstance(data, dict) and "questions" in data:
        questions = []
        for item in data.get("questions", []):
            if isinstance(item, dict):
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
            else:
                question = str(item).strip()
                answer = ""
            if question:
                questions.append({"question": question, "answer": answer})
        return {
            "type": "qa",
            "category": data.get("category"),
            "questions": questions,
        }

    if isinstance(data, dict):
        out = []
        for k, v in data.items():
            key = str(k).strip()
            val = str(v).strip()
            if key:
                out.append({"question": key, "answer": val})
        return {"type": "kv", "questions": out}

    if isinstance(data, list):
        questions = []
        for item in data:
            question = str(item).strip()
            if question:
                questions.append({"question": question, "answer": ""})
        return {"type": "list", "questions": questions}

    return {"type": "raw", "raw": health.checklist_json}
