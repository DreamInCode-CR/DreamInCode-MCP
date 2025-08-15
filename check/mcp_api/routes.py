from flask import request, jsonify
from mcp.core import procesar_mensaje

def configurar_rutas(app):

    
    @app.get("/")
    def home():
        return "DreamInCode API OK"

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="api")

    @app.route("/mcp", methods=["POST"])
    def mcp():
        data = request.json
        mensaje_usuario = data.get("mensaje", "")
        usuario_id = data.get("usuario_id", 3)
        respuesta = procesar_mensaje(mensaje_usuario, usuario_id)
        return jsonify({"respuesta": respuesta})
