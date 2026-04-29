import base64
import hashlib
import time
from datetime import datetime
from pathlib import Path

from config import SECRET_KEY, SIGNATURE_DIR


def now_utc() -> datetime:
    return datetime.utcnow()


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with fp.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def save_signature_image(data_url: str, ticket_id: int) -> str | None:
    if not data_url:
        return None

    prefix = "base64,"
    idx = data_url.find(prefix)
    if idx == -1:
        return None

    try:
        raw = base64.b64decode(data_url[idx + len(prefix):], validate=True)
    except Exception:
        return None

    digest = hashlib.sha256(raw + str(ticket_id).encode("utf-8") + SECRET_KEY.encode("utf-8")).hexdigest()
    filename = f"sig_{ticket_id}_{int(time.time())}_{digest[:10]}.png"
    path = SIGNATURE_DIR / filename
    try:
        path.write_bytes(raw)
    except Exception:
        return None

    return filename
