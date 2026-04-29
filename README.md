# Smart AI Ticket Management System — Simplified Docker Prototype (FYP1)

This prototype focuses only on the **core workflow** (no extra “architecture showcase” content in the UI):

- **Requester (no login)**: submit a ticket → get **Ticket ID + tracking link**
- **Tracking page**: view ticket details, status, public replies, attachments
- **AI triage (optional)**: if `GEMINI_API_KEY` is set, the system generates summary/category/priority/skill-group + suggested solution; otherwise it uses a stub
- **AI health check questions (optional)**: if `GEMINI_API_KEY` is set, the technician health checklist is generated per ticket; otherwise it uses the built-in fallback list
- **Technician**: login → view assigned tickets → update status → reply (public/internal) → upload attachments → upload proof-of-fix
- **Closure verification gate (aligned with your latest flow)**:
  1) proof-of-fix uploaded
  2) health verification checklist recorded (PASS) **or** admin supervisor override
  3) requester confirms closure by drawing an **e-sign** on the tracking page

> Important: your previous zip contained a real API key in `.env`. **Revoke that key** and replace it with a new one before you ever use it again.

---

## Run

1. Extract the zip
2. (Optional) copy `.env.example` → `.env` and fill what you need
3. Start:

```bash
docker compose up --build
```

Open: http://localhost:8080

### If you ran the older prototype before
The schema changed. Reset the old MySQL volume:

```bash
docker compose down -v
```

---

## Demo accounts (auto-seeded)

- **Admin**: `admin@demo.local` / `admin123`
- **Technicians**: `net@demo.local`, `hw@demo.local`, `sw@demo.local`, `print@demo.local` / `tech123`

---

## Notes

- File integrity: attachments store a **SHA-256** hash (watermarking is not implemented in this prototype).
- Security is prototype-level only (do not deploy publicly).
