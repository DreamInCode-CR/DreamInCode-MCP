# mcp_api/routes.py
import os
import io
import base64
import tempfile
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, Response, send_file
from openai import OpenAI

# Tu lógica propia
from mcp.database import get_due_meds
from mcp.core import procesar_mensaje
from mcp.context import build_system_prompt

def configurar_rutas(app):
    api = Blueprint("api", __name__)

    # -------- Config desde variables de entorno --------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    CHAT_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    STT_MODEL      = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    TTS_MODEL      = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    VOICE          = os.getenv("OPENAI_VOICE", "alloy")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # -------------------- Helpers --------------------
    def _get_usuario_id(payload) -> int:
        return int(payload.get("usuario_id") or payload.get("UsuarioID") or 3)

    def _now_with_offset(offset_min: int | None) -> datetime:
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        return now_utc if offset_min is None else now_utc + timedelta(minutes=offset_min)

    def _build_spanish_reminder(nombre: str | None, medicamento: str, dosis: str | None, hora: str, ask_confirm: bool = True) -> str:
        quien = f"{nombre}, " if nombre else ""
        dosis_txt = f" {dosis}" if dosis else ""
        base = f"Hola {quien}es la hora de tomar {medicamento}{dosis_txt}. Son las {hora}. Por favor tómala con cuidado."
        if ask_confirm:
            base += " ¿Ya te la tomaste? Responde sí o no."
        return base

    def transcribir_audio(file_storage) -> str:
        data = file_storage.read()
        filename = file_storage.filename or "audio.wav"
        mimetype = file_storage.mimetype or "audio/wav"
        resp = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=(filename, data, mimetype),
        )
        return resp.text

    def synthesize_wav(texto: str, voice: str | None = None):
        """
        Intenta WAV (via extra_body) y cae a MP3 si no es posible.
        Devuelve: (audio_bytes, mime)
        """
        v = voice or VOICE

        # 1) Streaming + WAV via extra_body
        try:
            with client.audio.speech.with_streaming_response.create(
                model=TTS_MODEL,
                voice=v,
                input=texto,
                extra_body={"format": "wav"},
            ) as r:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                try:
                    r.stream_to_file(tmp.name)
                    with open(tmp.name, "rb") as f:
                        return f.read(), "audio/wav"
                finally:
                    try: os.remove(tmp.name)
                    except Exception: pass
        except Exception:
            pass

        # 2) No streaming + WAV via extra_body
        try:
            r = client.audio.speech.create(
                model=TTS_MODEL,
                voice=v,
                input=texto,
                extra_body={"format": "wav"},
            )
            return r.read(), "audio/wav"
        except Exception:
            pass

        # 3) Fallback MP3
        r = client.audio.speech.create(
            model=TTS_MODEL,
            voice=v,
            input=texto,
        )
        return r.read(), "audio/mpeg"

    # --- Clasificación confirmación ---
    def _classify_confirm_heuristic(text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return "unsure"
        yes_words = ["sí","si","ya","claro","por supuesto","listo","hecho","me la tomé","me la tome","ya la tomé","ya la tome","ya lo hice","la tomé","la tome"]
        no_words  = ["no","todavía no","aún no","aun no","después","luego","más tarde","mas tarde","no la tomé","no la tome","no lo hice"]
        if any(w in t for w in yes_words): return "yes"
        if any(w in t for w in no_words):  return "no"
        return "unsure"

    def _classify_confirm_llm(text: str) -> tuple[str, float]:
        try:
            system = (
                "Eres un clasificador muy estricto. "
                "Decide si la respuesta indica que el usuario YA se tomó el medicamento (yes), "
                "NO se lo ha tomado (no), o no es claro (unsure). "
                'Responde SOLO un JSON como {"intent":"yes|no|unsure","confidence":0-1}.'
            )
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Respuesta del usuario: {text}"}
                ],
                temperature=0.0,
            )
            import json
            content = resp.choices[0].message.content.strip()
            data = json.loads(content)
            intent = data.get("intent", "unsure")
            conf = float(data.get("confidence", 0.5))
            if intent not in ("yes", "no", "unsure"):
                intent = "unsure"
            return intent, conf
        except Exception:
            return "unsure", 0.33

    def classify_confirmation(text: str) -> tuple[str, float]:
        first = _classify_confirm_heuristic(text)
        if first != "unsure":
            return first, 0.9 if first in ("yes", "no") else 0.5
        return _classify_confirm_llm(text)

    # -------------------- Rutas --------------------
    @api.get("/")
    def home():
        return "DreamInCode API OK"

    @api.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "api"})

    @api.post("/mcp")
    def mcp():
        data = request.get_json(silent=True) or {}
        mensaje_usuario = (data.get("mensaje") or "").strip()
        usuario_id = _get_usuario_id(data)
        system = build_system_prompt(usuario_id)
        respuesta = procesar_mensaje(mensaje_usuario, usuario_id, system_override=system)
        return jsonify({"respuesta": respuesta})

    @api.post("/stt")
    def stt():
        if "audio" not in request.files:
            return jsonify(error="Sube el archivo en form-data con la clave 'audio'"), 400
        _ = int(request.form.get("usuario_id") or request.form.get("UsuarioID") or 3)
        lang = request.form.get("lang")
        f = request.files["audio"]
        filename = f.filename or "audio.wav"
        mimetype = f.mimetype or "audio/wav"
        tr = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=(filename, f.read(), mimetype),
            language=lang
        )
        return jsonify({"transcripcion": tr.text})

    @api.post("/voice_mcp")
    def voice_mcp():
        if "audio" not in request.files:
            return jsonify(error="faltó 'audio' en form-data"), 400
        audio_file = request.files["audio"]
        usuario_id = request.form.get("usuario_id")
        retorno = (request.form.get("return") or "audio").strip().lower()

        try:
            texto = transcribir_audio(audio_file)
            system = build_system_prompt(usuario_id)
            respuesta_texto = procesar_mensaje(texto, usuario_id, system_override=system)
        except Exception as e:
            app.logger.exception("Error en STT o LLM")
            return jsonify(error="processing_failed", detail=str(e)), 500

        if retorno == "json":
            return jsonify({"transcript": texto, "reply": respuesta_texto})

        try:
            audio_bytes, mime = synthesize_wav(respuesta_texto)
        except Exception as e:
            app.logger.exception("Error en TTS")
            return jsonify(error="tts_failed", detail=str(e)), 500

        ext = "wav" if mime == "audio/wav" else "mp3"
        return send_file(
            io.BytesIO(audio_bytes),
            mimetype=mime,
            as_attachment=False,
            download_name=f"reply.{ext}",
        )

    @api.post("/tts")
    def tts():
        data = request.get_json(silent=True) or {}
        texto = (data.get("texto") or "").strip()
        if not texto:
            return jsonify(error="Falta 'texto'"), 400
        voice = data.get("voice") or VOICE
        try:
            audio_bytes, mime = synthesize_wav(texto, voice)
        except Exception as e:
            app.logger.exception("Error en TTS")
            return jsonify(error="tts_failed", detail=str(e)), 500
        ext = "wav" if mime == "audio/wav" else "mp3"
        return Response(
            audio_bytes,
            mimetype=mime,
            headers={"Content-Disposition": f'inline; filename="tts.{ext}"'}
        )

    @api.get("/meds/due")
    def meds_due():
        try:
            usuario_id = int(request.args.get("usuario_id"))
        except (TypeError, ValueError):
            return jsonify(error="usuario_id requerido"), 400

        window = int(request.args.get("window_min", 5))
        tz_offset = request.args.get("tz_offset_min")
        tz_offset = int(tz_offset) if tz_offset not in (None, "") else None

        now_local = _now_with_offset(tz_offset)
        items = get_due_meds(usuario_id, now_local, window)

        return jsonify({
            "usuario_id": usuario_id,
            "now_local": now_local.isoformat(),
            "window_min": window,
            "items": items
        })

    @api.post("/reminder_tts")
    def reminder_tts():
        data = request.get_json(silent=True) or {}
        usuario_id = int(data.get("usuario_id") or 0) or None
        auto = bool(data.get("auto"))
        tz_offset = data.get("tz_offset_min")
        tz_offset = int(tz_offset) if tz_offset not in (None, "") else None

        try:
            if auto:
                if not usuario_id:
                    return jsonify(error="auto=true requiere usuario_id"), 400
                now_local = _now_with_offset(tz_offset)
                due = get_due_meds(usuario_id, now_local, window_min=5)
                if not due:
                    return jsonify(error="No hay medicamentos para este momento."), 404
                item = due[0]
                medicamento = item["medicamento"]
                dosis = item.get("dosis")
                hora = item["hora"]
                nombre = item.get("usuario_nombre")
            else:
                medicamento = (data.get("medicamento") or "").strip()
                dosis = (data.get("dosis") or "").strip() or None
                hora = (data.get("hora") or "").strip()
                nombre = None
                if not medicamento or not hora:
                    return jsonify(error="Faltan campos: 'medicamento' y 'hora'"), 400

            texto = _build_spanish_reminder(nombre, medicamento, dosis, hora)
            audio_bytes, mime = synthesize_wav(texto, VOICE)

            if request.args.get("mode") == "json":
                return jsonify({
                    "usuario_id": usuario_id,
                    "medicamento": medicamento,
                    "dosis": dosis,
                    "hora": hora,
                    "tts_texto": texto,
                    "audio_mime": mime,
                    "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
                })

            ext = "wav" if mime == "audio/wav" else "mp3"
            resp = send_file(
                io.BytesIO(audio_bytes),
                mimetype=(mime or "audio/wav"),
                as_attachment=True,
                download_name=f"reminder.{ext}",
            )
            resp.headers["X-Usuario-Id"] = str(usuario_id) if usuario_id else ""
            resp.headers["X-Medicamento"] = medicamento
            resp.headers["X-Dosis"] = dosis or ""
            resp.headers["X-Hora"] = hora
            return resp
        except Exception as e:
            app.logger.exception("reminder_tts failed")
            return jsonify(error="reminder_tts_failed", detail=str(e)), 500

    @api.post("/confirm_intake")
    def confirm_intake():
        data = request.get_json(silent=True) or {}
        usuario_id = request.form.get("usuario_id") or data.get("usuario_id")
        medicamento = request.form.get("medicamento") or data.get("medicamento") or ""
        hora = request.form.get("hora") or data.get("hora") or ""
        want = (request.form.get("return") or data.get("return") or "audio").lower()

        if "audio" in request.files:
            try:
                texto = transcribir_audio(request.files["audio"])
            except Exception as e:
                app.logger.exception("STT error en confirm_intake")
                return jsonify(error="stt_failed", detail=str(e)), 500
        else:
            texto = (data.get("texto") or "").strip()

        intent, conf = classify_confirmation(texto)
        status = {"yes": "taken", "no": "missed", "unsure": "unclear"}[intent]

        if want == "json":
            speak = (
                "Perfecto. He registrado que tomaste tu medicamento. ¡Bien hecho!"
                if intent == "yes" else
                "De acuerdo. Te recordaré más tarde. Por favor, no lo olvides."
                if intent == "no" else
                "No te escuché bien. ¿La tomaste? Responde sí o no."
            )
            return jsonify({
                "transcript": texto,
                "intent": intent,
                "confidence": conf,
                "status": status,
                "speak": speak
            })

        try:
            speak = (
                "Perfecto. He registrado que tomaste tu medicamento. ¡Bien hecho!"
                if intent == "yes" else
                "De acuerdo. Te recordaré más tarde. Por favor, no lo olvides."
                if intent == "no" else
                "No te escuché bien. ¿La tomaste? Responde sí o no."
            )
            audio_bytes, mime = synthesize_wav(speak, VOICE)
        except Exception as e:
            app.logger.exception("TTS error en confirm_intake")
            return jsonify(error="tts_failed", detail=str(e)), 500

        ext = "wav" if mime == "audio/wav" else "mp3"
        return send_file(
            io.BytesIO(audio_bytes),
            mimetype=mime,
            as_attachment=False,
            download_name=f"confirm.{ext}",
        )

    @api.get("/meds/all")
    def meds_all():
        try:
            usuario_id = int(request.args.get("usuario_id") or os.getenv("DEFAULT_USUARIO_ID", 3))
        except (TypeError, ValueError):
            return jsonify(error="usuario_id inválido"), 400

        try:
            from mcp.database import get_all_meds
            items = get_all_meds(usuario_id)
            return jsonify({
                "usuario_id": usuario_id,
                "count": len(items),
                "items": items
            })
        except Exception as e:
            app.logger.exception("error en /meds/all")
            return jsonify(error="db_failure", detail=str(e)), 500

    app.register_blueprint(api, url_prefix="/")
