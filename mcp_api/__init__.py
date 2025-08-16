# mcp_api/__init__.py
from flask import Flask
from .routes import configurar_rutas

def create_app():
    app = Flask(__name__)
    # límite para subir audio (STT)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB
    configurar_rutas(app)
    return app
