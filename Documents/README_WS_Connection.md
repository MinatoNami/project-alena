# Local AI Gateway with FastAPI, WireGuard, and Nuxt

This repository documents a **working local AI architecture** where:

- **Nuxt frontend** runs on a MacBook
- **FastAPI gateway** runs on a Windows PC
- **Whisper + Ollama** run locally (never exposed to the internet)
- **WireGuard VPN** securely connects Mac ↔ Windows
- **HTTPS + WSS** are used end-to-end for browser compatibility

This setup is production-correct, browser-safe, and WebRTC-ready.

---

## Architecture Overview

```
Browser (Mac / Mobile)
   │ HTTPS / WSS
   ▼
Nuxt Frontend (Mac)
   │ WSS (WireGuard IP)
   ▼
FastAPI Gateway (Windows, TLS)
   │
   ├── Whisper (localhost)
   └── Ollama (localhost:11434)
```

Key properties:

- No port forwarding
- No ngrok required
- Ollama & Whisper remain private
- Browser security constraints satisfied

---

## Prerequisites

### Mac

- Node.js
- Nuxt 3
- WireGuard client
- mkcert

### Windows

- Python 3.10+
- FastAPI + Uvicorn
- WireGuard
- mkcert
- Ollama
- Whisper

---

## WireGuard

Ensure both machines are connected via WireGuard.

Example IPs:

```
Windows: <WIREGUARD_SERVER_IP>
Mac:     <WIREGUARD_CLIENT_IP>
```

Test from Mac:

```bash
ping <WIREGUARD_SERVER_IP>
```

---

## TLS with mkcert (Windows → Mac trust)

### On Windows

Generate cert for WireGuard IP:

```powershell
mkcert <WIREGUARD_SERVER_IP>
```

Find CA root:

```powershell
mkcert -CAROOT
```

Copy `rootCA.pem` to the Mac.

---

### On Mac

Trust the Windows mkcert CA:

```bash
sudo security add-trusted-cert \
  -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/Downloads/rootCA.pem
```

Restart browser after this step.

---

## FastAPI Gateway (Windows)

### Example app

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    while True:
        data = await ws.receive_text()
        await ws.send_text("ok")
```

### Run with TLS (IMPORTANT: no --reload on Windows)

```powershell
python -m uvicorn app.main:app \
  --host <BIND_HOST> \
  --port 8001 \
  --ssl-certfile certs/server.pem \
  --ssl-keyfile certs/server-key.pem
```

⚠️ Do NOT use `--reload` with SSL on Windows.  
It causes TLS handshake failures (`ERR_SSL_PROTOCOL_ERROR`).

---

## Windows Firewall

Allow inbound traffic on the gateway port:

```powershell
netsh advfirewall firewall add rule \
  name="FastAPI Gateway 8001" \
  dir=in action=allow protocol=TCP localport=8001
```

---

## Verification

### From Mac browser

```text
https://<WIREGUARD_SERVER_IP>:8001/health
```

Expected:

```json
{ "ok": true }
```

### WebSocket test

```bash
npm install -g wscat
wscat -n -c wss://<WIREGUARD_SERVER_IP>:8001/ws
```

---

## Nuxt Frontend

### Environment variable

```env
NUXT_PUBLIC_WS_URL=wss://<WIREGUARD_SERVER_IP>:8001/ws
```

### Client-side connection

```ts
onMounted(() => {
  const ws = new WebSocket(import.meta.env.NUXT_PUBLIC_WS_URL);

  ws.onopen = () => console.log("WSS connected");
  ws.onmessage = (e) => console.log(e.data);
  ws.onerror = (e) => console.error(e);
});
```

⚠️ Always run WebSocket code client-side only.

---

## Security Notes

- Never expose Ollama (11434) publicly
- Never expose Whisper directly
- Only the FastAPI gateway is reachable
- WireGuard restricts access to trusted peers
- TLS is required for browser audio + WebSocket APIs

---

## Next Steps

- Stream mic audio → Whisper
- Pipe Whisper output → Ollama
- Add auth (API key / JWT)
- Add cloud gateway for Vercel
- Migrate WebSocket → WebRTC

---

## Status

✅ Working  
✅ Secure  
✅ Browser-compatible  
✅ Ready for extension
