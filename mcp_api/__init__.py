from flask import Flask
from .routes import configurar_rutas

def create_app():
    app = Flask(__name__)
    configurar_rutas(app)
    return app