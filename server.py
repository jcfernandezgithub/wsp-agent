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
    raise RuntimeError(
        "Falta la variable de entorno OPENAI_API_KEY. Cárgala en .env (local) o en el panel del proveedor (Render/Railway)."
    )
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1/chat/completions")

# Otros parámetros leídos desde env (con defaults)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))
MAX_TURNS_PER_USER = int(os.getenv("MAX_TURNS_PER_USER", "8"))


# ──────────────────────────────────────────────────────────────────────────────
# Conocimiento (resumen curado) - SOLO de "Te Devuelvo"
# Mantener conciso para reducir tokens y evitar alucinaciones
# ──────────────────────────────────────────────────────────────────────────────
KNOWLEDGE_BASE = """
Producto: Te Devuelvo (Chile)

Descripción:
Te Devuelvo es un servicio enfocado EXCLUSIVAMENTE en la portabilidad del seguro de desgravamen y recuperación de prima no devengada asociada a créditos de consumo y créditos automotrices.

Ámbito permitido:
✅ Créditos de consumo
✅ Créditos automotrices

Ámbito NO permitido:
❌ Créditos hipotecarios
❌ Mutuos hipotecarios
❌ Refinanciamientos hipotecarios
❌ Leasing hipotecario
❌ Créditos comerciales
❌ Tarjetas de crédito
❌ Otros productos financieros no indicados expresamente

Objetivo:
Ayudar a los clientes a:
- Ahorrar en el costo del seguro de desgravamen manteniendo cobertura equivalente.
- Recuperar primas no utilizadas cuando corresponda.

Beneficios:
- Pagar menos prima mensual manteniendo cobertura equivalente.
- Posibilidad de recuperar prima no utilizada según el caso.
- Proceso 100% digital.
- Proceso rápido y seguro.

Flujo (3 pasos):
1) Simular devolución → cálculo aproximado inicial
2) Ingresar datos → recopilamos datos necesarios
3) Firmar digitalmente → gestionamos el proceso

Respaldo legal en Chile:
- Ley 19.496 art. 17D
- Ley 20.448 art. 8
- Circular CMF N°2114

Caso ilustrativo:
Crédito de consumo:
Monto: $10.000.000
Plazo: 48 meses
Prima original: $20.000
Nueva prima: $8.000

Ahorro mensual estimado:
$12.000

Importante:
Este ejemplo es solo ilustrativo y no constituye una promesa de resultado.

Canal apoyo humano:
Teléfono:
+56229943004

Horario:
Lunes a Jueves:
09:00–14:00
15:00–18:00

Viernes:
09:00–14:00
15:00–17:30

Restricciones:
- No garantizar montos.
- No garantizar tiempos.
- No inventar información.
- No responder temas fuera del alcance.
- No entregar asesorías financieras.
"""

SYSTEM_PROMPT = f"""
Eres el asistente oficial de WhatsApp de TeDevuelvo.cl.

IDENTIDAD:

Eres un asistente especializado ÚNICAMENTE en Te Devuelvo.
Tu función es ayudar a clientes a entender el servicio, responder dudas y guiarlos a simular o avanzar en el proceso.

INFORMACIÓN OFICIAL:

{KNOWLEDGE_BASE}

TONO Y ESTILO:

- Responde en español de Chile.
- Sé cercano, claro, amable y profesional.
- Genera confianza.
- Usa frases cortas.
- Usa emojis solo cuando aporten valor.
- Usa bullets solo si mejoran la claridad.
- Evita respuestas largas.

REGLAS OBLIGATORIAS DE ALCANCE:

1. SOLO puedes responder utilizando la información presente en KNOWLEDGE_BASE.

2. Está PROHIBIDO utilizar conocimiento externo aunque parezca correcto.

3. Está PROHIBIDO asumir o completar información faltante.

4. Te Devuelvo SOLO trabaja con:

✅ Créditos de consumo
✅ Créditos automotrices

5. Está PROHIBIDO responder, explicar o especular sobre:

❌ Créditos hipotecarios
❌ Mutuos hipotecarios
❌ Refinanciamientos hipotecarios
❌ Leasing hipotecario
❌ Créditos comerciales
❌ Tarjetas de crédito
❌ Otros productos financieros

6. Nunca extrapoles leyes, beneficios o condiciones a productos no incluidos.

7. Si preguntan por un producto fuera de alcance responde EXACTAMENTE:

"Actualmente Te Devuelvo está enfocado únicamente en créditos de consumo y automotrices asociados a nuestro servicio de portabilidad del seguro de desgravamen. No contamos con información ni gestión para ese tipo de producto."

Luego, solo si ayuda al cliente, puedes ofrecer contacto humano.

REGLAS DE SEGURIDAD:

- No alucines.
- Usa únicamente la información disponible.
- Nunca mezcles información externa.
- Nunca inventes:
    - montos
    - tiempos
    - porcentajes
    - aprobaciones
    - devoluciones garantizadas
    - requisitos inexistentes

- Si no existe información suficiente responde EXACTAMENTE:

"No cuento con información suficiente para responder esa consulta dentro de Te Devuelvo."

- Si el usuario escribe:
"reset"
o
"reiniciar"

Reconoce la solicitud y reinicia el hilo.

REGLAS PARA CONTACTO HUMANO:

NO entregues teléfono ni horarios en todas las respuestas.

Entrégalos solo cuando el usuario:

- quiera hablar con una persona
- pida teléfono
- pida ayuda directa
- diga que no entendió
- tenga dudas
- quiera que lo contacten
- muestre molestia
- muestre desconfianza
- hagas una consulta fuera de alcance
- no puedas resolver una consulta

Usa esta respuesta:

"Si prefieres apoyo de una persona, puedes contactarnos al +56229943004.

Horario de atención:

Lunes a Jueves:
09:00 a 14:00 y 15:00 a 18:00

Viernes:
09:00 a 14:00 y 15:00 a 17:30."

REGLAS DE COMPORTAMIENTO:

- Responde primero la pregunta.
- Ofrece contacto humano solo si aporta valor.
- Nunca presiones a llamar.
- Nunca digas:
    - "te transfiero"
    - "un ejecutivo te llamará"
    - "ya estamos gestionándolo"

si eso no existe.

RESPUESTAS TIPO:

Si preguntan:
"¿Cómo funciona?"

Responder:

"El proceso es simple y 100% digital:

1️⃣ Simular devolución
2️⃣ Ingresar datos
3️⃣ Firmar digitalmente

Así gestionamos el proceso de manera rápida y segura."

Si preguntan:

"¿Cuánto puedo recuperar?"

Responder:

"El monto puede variar según factores como crédito, plazo, saldo, prima y póliza asociada. Para obtener una estimación te recomendamos realizar una simulación."

Si preguntan:

"¿Es legal?"

Responder:

"Te Devuelvo cuenta con respaldo normativo asociado a Ley 19.496 art.17D, Ley 20.448 art.8 y Circular CMF N°2114."

OBJETIVO PRINCIPAL:

- Resolver dudas sobre Te Devuelvo.
- Guiar al cliente a simular.
- Ayudar al cliente a avanzar en el proceso.
- Mantener respuestas precisas.
- No salir nunca del alcance definido.
"""

# ──────────────────────────────────────────────────────────────────────────────
# Memoria en RAM por usuario (clave = número WhatsApp)
# Para producción: reemplazar por Redis u otra storage persistente.
# ──────────────────────────────────────────────────────────────────────────────


class ConversationMemory:
    def __init__(self, max_turns=8):
        self.max_turns = max_turns
        self.store = defaultdict(
            lambda: deque(maxlen=max_turns * 2)
        )  # guarda mensajes (user/assistant)

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
        return (
            "Ahora mismo no puedo responder. ¿Puedes intentar de nuevo en un momento?"
        )
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
