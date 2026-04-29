import json
import logging
import re

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

TRIAGE_CATEGORIES = ["Network", "Printer", "Account", "Hardware", "Software"]
TRIAGE_PRIORITIES = ["Low", "Medium", "High", "Critical"]
TRIAGE_SKILL_GROUPS = TRIAGE_CATEGORIES + ["General"]
AI_RESPONSE_KEYS = {
    "summary",
    "category",
    "priority",
    "suggested_technician_skill_group",
    "solution_suggestion",
}

DEFAULT_FALLBACK_CATEGORY = "Software"
DEFAULT_FALLBACK_PRIORITY = "Medium"
DEFAULT_FALLBACK_SKILL_GROUP = "General"


def _sanitize_summary(text: str, fallback: str) -> str:
    value = (text or "").strip()
    if not value:
        return fallback
    value = re.sub(
        r"^(requester reported|user reported|customer reported|reported issue|issue summary|summary|issue)\s*:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value or fallback


def _sanitize_solution(text: str, fallback: str) -> str:
    value = (text or "").strip()
    if not value:
        return fallback

    cleaned_lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"^\d+[\).\s-]+", "", line)
        line = re.sub(r"^(solution|recommended resolution|resolution|steps)\s*:\s*", "", line, flags=re.IGNORECASE)
        if line:
            cleaned_lines.append(line)

    if not cleaned_lines:
        return fallback
    return "\n".join(cleaned_lines)


def _fallback_summary(issue_title: str, reason: str) -> str:
    base_summary = _sanitize_summary(issue_title, "Ticket details require manual review.")
    return f"{base_summary} AI currently not available for automated triage. {reason}"


def _fallback_solution(reason: str) -> str:
    return (
        "AI currently not available for automated triage.\n"
        f"{reason}\n"
        "Review the ticket title and description manually.\n"
        "Confirm the category, priority, and technician skill group before proceeding."
    )


def _fallback_triage(issue_title: str, reason: str, raw_response: str | None = None) -> dict:
    return {
        "summary": _fallback_summary(issue_title, reason),
        "category": DEFAULT_FALLBACK_CATEGORY,
        "priority": DEFAULT_FALLBACK_PRIORITY,
        "skill_group": DEFAULT_FALLBACK_SKILL_GROUP,
        "solution": _sanitize_solution(
            _fallback_solution(reason),
            "AI currently not available for automated triage.",
        ),
        "_model": None,
        "_raw": raw_response,
    }


def _build_prompt(issue_title: str, description: str) -> str:
    return f"""
You are an IT helpdesk triage assistant.

Read the ticket title and description and perform the classification directly.
Return strict JSON only.
Do not explain yourself.
Do not return markdown.
Do not return any text before or after the JSON.

Return exactly this JSON object:
{{
  "summary": "...",
  "category": "...",
  "priority": "...",
  "suggested_technician_skill_group": "...",
  "solution_suggestion": "..."
}}

Rules:
- category must be exactly one of: {', '.join(TRIAGE_CATEGORIES)}
- priority must be exactly one of: {', '.join(TRIAGE_PRIORITIES)}
- choose priority using these business rules, not general judgment:
  Low = minor issue, little impact, workaround exists
  Medium = normal support issue, affects one user or limited work
  High = serious issue, important work blocked, no easy workaround
  Critical = major outage, many users affected, core business operation disrupted
- suggested_technician_skill_group must be exactly one of: {', '.join(TRIAGE_SKILL_GROUPS)}
- summary must be concise and based only on the ticket title and description
- solution_suggestion must be a concise actionable suggestion based only on the ticket title and description

Ticket title: {issue_title}
Ticket description: {description}
""".strip()


def _parse_and_validate_ai_response(raw_text: str) -> dict:
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("AI triage response must be a JSON object.")

    if set(parsed.keys()) != AI_RESPONSE_KEYS:
        raise ValueError("AI triage response keys do not match the required JSON structure.")

    summary = _sanitize_summary(
        parsed.get("summary", ""),
        "Ticket details require manual review.",
    )
    category = (parsed.get("category") or "").strip()
    priority = (parsed.get("priority") or "").strip()
    skill_group = (parsed.get("suggested_technician_skill_group") or "").strip()
    solution = _sanitize_solution(
        parsed.get("solution_suggestion", ""),
        "Review the ticket manually and continue standard troubleshooting.",
    )

    if category not in TRIAGE_CATEGORIES:
        raise ValueError(f"Invalid AI triage category: {category!r}")
    if priority not in TRIAGE_PRIORITIES:
        raise ValueError(f"Invalid AI triage priority: {priority!r}")
    if skill_group not in TRIAGE_SKILL_GROUPS:
        raise ValueError(f"Invalid AI triage skill group: {skill_group!r}")

    return {
        "summary": summary,
        "category": category,
        "priority": priority,
        "skill_group": skill_group,
        "solution": solution,
    }


def triage_with_gemini(issue_title: str, description: str) -> dict:
    """Return dict: summary, category, priority, skill_group, solution.

    AI triage is primary. If AI is unavailable or returns invalid JSON, return a safe fallback.
    """
    if not GEMINI_API_KEY:
        return _fallback_triage(issue_title, "AI service is not configured.")

    prompt = _build_prompt(issue_title, description)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    raw_text = None

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
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        triage = _parse_and_validate_ai_response(raw_text)
        triage["_model"] = GEMINI_MODEL
        triage["_raw"] = json.dumps(data, ensure_ascii=False)
        return triage
    except json.JSONDecodeError:
        logger.exception("Gemini triage returned invalid JSON; using fallback triage.")
        return _fallback_triage(
            issue_title,
            "The AI response was not valid JSON.",
            raw_response=raw_text,
        )
    except ValueError:
        logger.exception("Gemini triage returned invalid values; using fallback triage.")
        return _fallback_triage(
            issue_title,
            "The AI response did not match the required category, priority, or JSON structure.",
            raw_response=raw_text,
        )
    except Exception:
        logger.exception("Gemini triage request failed; using fallback triage.")
        return _fallback_triage(
            issue_title,
            "The AI service request failed.",
        )
