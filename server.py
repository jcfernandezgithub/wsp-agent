# server.py
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import requests, os, time
from collections import deque, defaultdict

app = Flask(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Falta la variable de entorno OPENAI_API_KEY. Cárgala en .env (local) o en el panel del proveedor (Render/Railway).")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1/chat/completions")

# Otros parámetros leídos desde env (con defaults)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))

# ──────────────────────────────────────────────────────────────────────────────
# Conocimiento (resumen curado) - SOLO de "Te Devuelvo"
# Mantener conciso para reducir tokens y evitar alucinaciones
# ──────────────────────────────────────────────────────────────────────────────
KNOWLEDGE_BASE = """
Producto: Te Devuelvo (Chile)
Objetivo: Ahorrar en el seguro de desgravamen de créditos (consumo, automotriz, u otros) y recuperar prima no devengada al portar el seguro.

Beneficios:
- Pagar menos prima mensual al cambiar de aseguradora manteniendo cobertura equivalente.
- Obtener devolución de la prima no utilizada (clientes han recibido aprox. $322.000 a $1,4 millones; montos varían por caso).
- Proceso 100% digital, rápido y seguro.

Flujo (3 pasos):
1) Simular devolución → cálculo aproximado inmediato.
2) Ingresar datos → datos básicos para gestionar la portabilidad.
3) Firmar digitalmente → completamos la gestión.

Respaldo legal en Chile:
- Ley 19.496 art. 17D: permite terminar servicios financieros (incluye seguros) sin penalización si hay cumplimiento de obligaciones.
- Ley 20.448 art. 8: libertad para elegir aseguradora (no se puede condicionar el crédito a un proveedor único).
- Circular CMF N° 2114: obliga devolución de prima no devengada al terminar antes del vencimiento (pago máx. 10 días hábiles).

Caso real (ejemplo ilustrativo):
Crédito consumo $10.000.000 a 48 meses. Prima original $20.000/mes; nueva prima $8.000/mes.
Ahorro mensual $12.000 → $576.000 en 48 meses. Posible devolución de prima no devengada según condiciones.

Límites:
- No garantizamos montos específicos; cada caso depende del crédito, plazo, saldo, prima y póliza.
- No entregamos asesorías fuera del ámbito del producto ni información de otros servicios.
"""

# ──────────────────────────────────────────────────────────────────────────────
# Prompt de sistema con guardrails
# ──────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""
Eres el asistente oficial de WhatsApp de TeDevuelvo.cl.
Tono: cercano, claro, amable y profesional. Genera confianza. Responde en español de Chile.
Alcance: SOLO hablas del producto "Te Devuelvo" (portabilidad del seguro de desgravamen y devolución de prima no devengada). 
No opines de otros temas ni des consejos fuera de este alcance.

Instrucciones de seguridad y estilo:
- No alucines: si no hay información en la base, di que no cuentas con ese dato y ofrece escalar a un humano.
- Sé breve y ordenado (frases cortas, emojis moderados y útiles).
- Usa bullets cuando mejore la claridad.
- Incluye disclaimers cuando corresponda (p. ej., montos y tiempos pueden variar por caso).
- Nunca inventes cifras ni plazos; usa solo los confirmados.
- Si el usuario pide “reset” o “reiniciar”, reconoce y reinicia el hilo.

Información del producto (resumen verificado):
{KNOWLEDGE_BASE}

Respuestas tipo:
- Si preguntan “¿Cómo funciona?” → explica 3 pasos (Simular, Datos, Firma digital) + respaldo legal y que el proceso es digital y seguro.
- Si preguntan “¿Cuánto puedo recuperar?” → invita a simular, aclara que el monto depende del caso y da ejemplos ilustrativos (sin prometer).
- Si piden cosas fuera de alcance → “Puedo ayudarte solo con Te Devuelvo. ¿Te cuento cómo simular tu devolución?”
"""

# ──────────────────────────────────────────────────────────────────────────────
# Memoria en RAM por usuario (clave = número WhatsApp)
# Para producción: reemplazar por Redis u otra storage persistente.
# ──────────────────────────────────────────────────────────────────────────────

class ConversationMemory:
    def __init__(self, max_turns=8):
        self.max_turns = max_turns
        self.store = defaultdict(lambda: deque(maxlen=max_turns*2))  # guarda mensajes (user/assistant)

    def get_history(self, user_id):
        """Devuelve lista [{'role': 'user'|'assistant', 'content': '...'}, ...]"""
        return list(self.store[user_id])

    def append(self, user_id, role, content):
        self.store[user_id].append({"role": role, "content": content})

    def reset(self, user_id):
        self.store[user_id].clear()

MEMORY = ConversationMemory(MAX_TURNS_PER_USER)

# ── (Opcional) Redis para persistir memoria ───────────────────────────────────
# import redis, json
# REDIS_URL = os.getenv("REDIS_URL")
# rds = redis.from_url(REDIS_URL) if REDIS_URL else None
# def load_history(user_id):
#     if not rds: return MEMORY.get_history(user_id)
#     raw = rds.get(f"tdv:hist:{user_id}")
#     return json.loads(raw) if raw else []
# def save_history(user_id, history):
#     if not rds:
#         # volcar en MEMORY
#         MEMORY.reset(user_id)
#         for m in history[-MAX_TURNS_PER_USER*2:]:
#             MEMORY.append(user_id, m["role"], m["content"])
#         return
#     rds.setex(f"tdv:hist:{user_id}", 60*60*24*7, json.dumps(history))  # TTL 7 días

# ──────────────────────────────────────────────────────────────────────────────
# OpenAI
# ──────────────────────────────────────────────────────────────────────────────
def ask_openai(from_number: str, user_text: str) -> str:
    try:
        # Comando de reset sencillo
        if user_text.strip().lower() in {"reset", "reiniciar", "inicio"}:
            MEMORY.reset(from_number)
            return "Listo, reinicié la conversación. ¿Te explico cómo funciona Te Devuelvo en 3 pasos?"

        # Construir historial
        history = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Mensajes previos del usuario (memoria)
        previous = MEMORY.get_history(from_number)
        for msg in previous:
            # no incluir system previos; solo user/assistant
            if msg["role"] in ("user", "assistant"):
                history.append(msg)

        # Mensaje actual
        history.append({"role": "user", "content": user_text})

        payload = {
            "model": OPENAI_MODEL,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "messages": history,
        }

        r = requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if 200 <= r.status_code < 300:
            data = r.json()
            answer = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "Gracias por tu mensaje 🙌")
            ).strip()

            # Actualiza memoria (solo si éxito)
            MEMORY.append(from_number, "user", user_text)
            MEMORY.append(from_number, "assistant", answer)

            return answer

        print("OpenAI error:", r.status_code, r.text[:500])
        return "Ahora mismo no puedo responder. ¿Puedes intentar de nuevo en un momento?"
    except Exception as e:
        print("OpenAI exception:", e)
        return "Tuvimos un problema procesando tu mensaje."

# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/")
def health():
    return "ok"

@app.post("/webhook")
def webhook():
    from_number = (request.form.get("From") or "").strip()  # "whatsapp:+56..."
    text = (request.form.get("Body") or "").strip()

    if not text or not from_number:
        return ("", 200)

    answer = ask_openai(from_number, text)

    # TwiML simple
    resp = MessagingResponse()
    resp.message(answer)
    return Response(str(resp), mimetype="application/xml")

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)