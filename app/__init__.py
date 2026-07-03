"""Factory principal da aplicação Flask."""
from __future__ import annotations
import os
import logging
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user, login_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .core.extensions import db, login_manager
from .core.models import User, Cliente, Processo, Andamento, Prazo

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("lex_praxis")


def create_app(config_class=Config) -> Flask:
    static_dir = Path(__file__).resolve().parent / "web" / "static"
    app = Flask(__name__,
                instance_relative_config=False,
                static_folder=str(static_dir),
                static_url_path="/static")
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    instance_dir = Path(__file__).resolve().parent.parent / "instance"
    instance_dir.mkdir(exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_message = "Faça login para continuar."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    from .web import bp as web_bp
    from .api import bp as api_bp
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    with app.app_context():
        db.create_all()
        _criar_admin_inicial()

    return app


def _criar_admin_inicial():
    cfg = Config
    if User.query.filter_by(email=cfg.ADMIN_EMAIL).first():
        return
    admin = User(
        name=cfg.ADMIN_NAME,
        email=cfg.ADMIN_EMAIL,
        role="admin",
        active=True,
    )
    admin.set_password(cfg.ADMIN_PASSWORD)
    db.session.add(admin)
    db.session.commit()
    log.info("Usuário admin criado: %s", cfg.ADMIN_EMAIL)
