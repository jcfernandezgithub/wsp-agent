# Deploy WhatsApp Bot (Flask) en Render o Railway

## 0) Seguridad
- **Quita claves del código**. Usa variables de entorno. Nunca subas `.env` al repo.
- Si tu key quedó expuesta, **róta** la `OPENAI_API_KEY` en OpenAI.

## 1) Archivos incluidos
- `.env.example` → plantilla local
- `requirements.txt` → dependencias Python
- `render.yaml` → Blueprint opcional para Render
- `Dockerfile` → alternativa con contenedor (Railway o Render)
- `.gitignore`
- `server.py.patch` → parche para eliminar la key embebida y leer config desde env

## 2) Uso local
```bash
cp .env.example .env
# edita OPENAI_API_KEY en .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gunicorn -w 2 -k gthread -t 60 -b 0.0.0.0:5000 server:app
```
Prueba:
```bash
curl -X POST -d "From=whatsapp:+56911111111&Body=Hola" http://localhost:5000/webhook
```

## 3) Deploy en **Render** (sin Docker)
1. Sube estos archivos a tu repo.
2. En Render: **New → Blueprint** y apunta al repo (o **New → Web Service** si prefieres manual).
3. Si usas Blueprint, se leerá `render.yaml`. Si no:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn -w 2 -k gthread -t 60 -b 0.0.0.0:$PORT server:app`
   - **Health Check Path:** `/`
4. **Environment Variables:** agrega `OPENAI_API_KEY` (y otras si quieres).
5. Render asignará una URL pública: `https://<tu-servicio>.onrender.com`.

## 4) Deploy en **Railway**
**Opción A — Nixpacks (sin Docker):**
- Conecta el repo → Railway detecta Python.
- **Start Command:** `gunicorn -w 2 -k gthread -t 60 -b 0.0.0.0:$PORT server:app`
- En **Variables**, añade `OPENAI_API_KEY`, etc.

**Opción B — con Dockerfile (incluido):**
- Conecta el repo. Railway construye el contenedor.
- Asegúrate de definir las Variables de entorno (OPENAI_API_KEY, ...).

Cuando esté desplegado, tendrás una URL tipo `https://<subdominio>.up.railway.app`.

## 5) Conectar **Twilio WhatsApp**
1. Entra a Twilio Console → WhatsApp (Sandbox o tu número verificado).
2. En “WHEN A MESSAGE COMES IN” configura:
   - **POST** a `https://<tu-servicio>/webhook`
3. Prueba:
   ```bash
   curl -X POST        -d "From=whatsapp:+56911111111&Body=Hola"        https://<tu-servicio>/webhook
   ```

## 6) Persistencia (opcional)
- Para no perder historial en reinicios, usa Redis administrado.
- Configura `REDIS_URL` en el proveedor y adapta las funciones comentadas en `server.py`.

---
**Tip:** Si Render/Railway tardan en hacer “spin-up” en plan free, puedes configurar un monitor externo con ping periódico a `/` para mantenerlo caliente.
