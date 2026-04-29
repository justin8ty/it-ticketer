import time
from pathlib import Path

from werkzeug.utils import secure_filename

from config import UPLOAD_DIR
from models import Attachment
from utils import sha256_file


def save_attachment(
    file,
    ticket_id: int,
    attachment_type: str,
    uploaded_by_role: str,
    uploaded_by_id: int | None,
) -> Attachment | None:
    filename = secure_filename(file.filename)
    if not filename:
        return None

    ticket_dir = UPLOAD_DIR / str(ticket_id)
    ticket_dir.mkdir(parents=True, exist_ok=True)

    dest = ticket_dir / f"{int(time.time())}_{filename}"
    file.save(dest)

    digest = sha256_file(dest)

    uploaded_by_requester_id = None
    uploaded_by_technician_id = None
    if uploaded_by_role == "Requester":
        uploaded_by_requester_id = uploaded_by_id
    elif uploaded_by_role == "Technician":
        uploaded_by_technician_id = uploaded_by_id

    return Attachment(
        ticket_id=ticket_id,
        attachment_name=filename,
        attachment_path=str(dest),
        attachment_hash=digest,
        attachment_type=attachment_type,
        uploaded_by_requester_id=uploaded_by_requester_id,
        uploaded_by_technician_id=uploaded_by_technician_id,
    )
