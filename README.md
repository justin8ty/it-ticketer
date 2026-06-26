# Smart AI Ticket Management System

This is a web-based IT support ticket management system developed for FYP2.
It supports requester ticket submission, AI triage, technician handling, admin monitoring, and closure verification.

## Main Features

* Requester can submit ticket without login
* Requester receives Ticket ID and private tracking link
* Requester can track ticket status using the tracking link
* Gemini AI can generate ticket summary, category, priority, technician skill group, and suggested solution
* Technician can view assigned tickets, update status, reply, upload attachments, and upload proof-of-fix
* Admin can monitor tickets, manage technician accounts, edit allowed ticket fields, and view logs
* Ticket closure requires proof-of-fix, health verification, and requester e-sign confirmation
* Email and Telegram notification are supported depending on configuration

## Technology Used

* Python Flask
* HTML, CSS, JavaScript
* SQLite
* SQLAlchemy
* Gemini API
* Docker
* Gunicorn
* Render

## How to Run Locally

1. Open the project folder:

```bash
cd it-ticketer
```

2. Copy `.env.example` to `.env` and update the settings if needed.

3. Start the system:

```bash
docker compose up --build
```

4. Open in browser:

```text
http://localhost:8080
```

## Demo Accounts

Admin:

```text
admin@demo.local / admin123
```

Technicians:

```text
net@demo.local / tech123
hw@demo.local / tech123
sw@demo.local / tech123
print@demo.local / tech123
```

## Database

The system uses SQLite.
Inside Docker, the database file is stored at:

```text
/app/data/ticketdb.sqlite3
```

To copy the database file out:

```bash
docker compose cp web:/app/data/ticketdb.sqlite3 ./ticketdb.sqlite3
```

## Online Deployment

The system is deployed on Render for FYP demonstration and testing.

```text
Browser → Render Flask App → SQLite database file
```

The online version is not meant for long-term production storage because the SQLite database and uploaded files are stored inside the Render environment.

## Notes

* Do not upload real API keys or passwords to GitHub.
* Requester tracking uses a private tracking token.
* Public replies are visible to requester.
* Internal notes are only visible to staff.
* Admin actions are recorded in the action log.
