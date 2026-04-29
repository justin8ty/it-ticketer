from flask import Flask

from roles_auth import login_manager
from config import APP_PORT, SECRET_KEY
from db import Base, db_retry, engine, migrate_schema
from routes_admin import register_admin_routes
from routes_public import register_public_routes
from routes_tech import register_tech_routes
from tickets import ensure_seed_data


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    login_manager.init_app(app)

    register_public_routes(app)
    register_tech_routes(app)
    register_admin_routes(app)
    return app


def init_app() -> None:
    db_retry()
    migrate_schema()
    Base.metadata.create_all(engine)
    ensure_seed_data()


app = create_app()


if __name__ == "__main__":
    init_app()
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
