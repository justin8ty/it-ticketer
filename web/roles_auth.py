from flask import flash, redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required

from db import SessionLocal
from models import Admin, Technician

login_manager = LoginManager()
login_manager.login_view = "tech_login"


@login_manager.unauthorized_handler
def _unauthorized():
    path = request.path or ""
    if path.startswith("/admin"):
        return redirect(url_for("admin_login"))
    return redirect(url_for("tech_login"))


class AuthUser(UserMixin):
    def __init__(self, role: str, user_id: int, email: str, name: str):
        self.role = role
        self.id = f"{role}:{user_id}"
        self.user_id = user_id
        self.email = email
        self.name = name

    def get_id(self):
        return self.id


@login_manager.user_loader
def load_user(user_key: str):
    try:
        role, raw_id = user_key.split(":", 1)
        user_id = int(raw_id)
    except Exception:
        return None

    db = SessionLocal()
    try:
        if role == "tech":
            t = db.query(Technician).filter(Technician.id == user_id).first()
            if not t or not t.is_active:
                return None
            return AuthUser("tech", t.id, t.email, t.name)
        if role == "admin":
            a = db.query(Admin).filter(Admin.id == user_id).first()
            if not a or not a.is_active:
                return None
            return AuthUser("admin", a.id, a.email, a.name)
        return None
    finally:
        db.close()


def require_role(role: str):
    def decorator(fn):
        @login_required
        def wrapper(*args, **kwargs):
            if getattr(current_user, "role", None) != role:
                flash("Access denied (wrong role).", "danger")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator
