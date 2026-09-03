# Reaching the services: Tailscale, TLS, and the browser

How the pieces find each other, and the browser constraints that shape the
setup.

> Superseded: this used to describe WireGuard between a Mac and a Windows PC
> running Ollama and Whisper locally. Both moved — inference to LM Studio,
> transcription to text-whisperer — and the transport is Tailscale now.

---

## Topology

```
Browser (Mac / iPhone)
   │ HTTPS / WSS
   ▼
Nuxt frontend
   │ HTTPS / WSS
   ▼
Voice Assistant backend (FastAPI)          ← the only thing the browser talks to
   │
   ├── POST /api/transcribe ──► text-whisperer      (Mac, MLX Whisper on Metal)
   ├── POST /v1/chat/completions ──► LM Studio      (:1234)
   └── POST /generate ──► ALENA controller ──► MCP tools
```

Properties worth keeping:

- No port forwarding and no tunnelling service.
- LM Studio and text-whisperer are never reachable from the browser. The
  backend is the only public surface, and it is only public on the tailnet.
- Every hop is inside the tailnet, which is encrypted and device-authenticated.

---

## Tailscale

Machines address each other by name. `tailscale status` lists them:

```
macbook-pro-m5-max        this machine
macbook-pro-14-m4-pro     text-whisperer (Apple GPU)
alena-server              gateway + long-running services
```

So `TEXT_WHISPERER_URL=http://macbook-pro-14-m4-pro:8090` just works from any
machine on the tailnet, with no VPN config to maintain.

### Publishing a loopback service

text-whisperer binds `127.0.0.1` deliberately. Publish it with `tailscale
serve` rather than rebinding it to `0.0.0.0` — that way it is reachable by
tailnet identity, over TLS, and never by anything on the LAN:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8090
```

Set its `WEB_PASSWORD` before doing this. Without one, every transcript it has
ever made is readable by anything on the tailnet.

---

## TLS and the browser

`getUserMedia` — the microphone — only works on a secure context. `localhost`
counts; a tailnet hostname does not. So either:

1. **Let Tailscale terminate TLS** (`tailscale serve`, above). It provisions a
   real certificate for the `.ts.net` name, so nothing has to be trusted by
   hand. This is the easy path.
2. **Use mkcert** for a local certificate, if you are running the backend
   directly and reaching it by hostname or IP.

### mkcert

On the machine serving:

```bash
mkcert -install
mkcert -cert-file certs/server.pem -key-file certs/server-key.pem localhost
```

`scripts/start_server.sh` picks those up automatically and starts with TLS if
they exist. Copy the CA (`mkcert -CAROOT`) to any other machine that has to
trust it:

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain ~/Downloads/rootCA.pem
```

Restart the browser afterwards.

`*.pem` is gitignored. If any were committed before that:

```bash
git rm --cached -r -- '**/*.pem'
```

---

## Verifying

```bash
# The backend, and whether it can see text-whisperer
curl -s http://localhost:8001/health | jq

# Inference
curl -s http://localhost:1234/v1/models | jq '.data[].id'

# The audio WebSocket
npm install -g wscat
wscat -c ws://localhost:8001/ws
```

`/health` reports `stt.reachable`. When voice input goes quiet, that is the
first thing to look at — it is nearly always the Mac asleep or off the tailnet
rather than a bug in the pipeline.

---

## Security notes

- Never bind LM Studio or text-whisperer to `0.0.0.0`.
- The backend is the only service the browser reaches; keep it that way.
- Set `WEB_PASSWORD` on text-whisperer and pass it as `TEXT_WHISPERER_TOKEN`.
- A loopback address is not proof the work is local: LM Studio can be *linked*
  to another machine, so `127.0.0.1:1234` may be forwarding your prompts
  elsewhere. `lms ps` shows the device a model actually runs on.

---

## Next steps

- Live partial transcripts (needs VAD + windowed decode on the MLX side)
- Auth on the backend beyond tailnet membership
- Migrate the audio WebSocket to WebRTC
