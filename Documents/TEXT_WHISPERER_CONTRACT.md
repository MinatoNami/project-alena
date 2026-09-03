# text-whisperer transcription endpoint

ALENA no longer runs Whisper. It sends audio to
[text-whisperer](https://github.com/MinatoNami/text-whisperer) over the tailnet
and gets a transcript back.

The client lives in
[`modules/stt/text_whisperer.py`](../modules/stt/text_whisperer.py); the
endpoint is implemented in text-whisperer's `src/telegram_stt/web.py`
(`_do_transcribe`) with upload parsing in its `multipart.py`. This file is the
contract both sides are written against — change it when they change.

---

## Why an endpoint rather than a stream

text-whisperer's only ingest path today is its Telegram poll loop. `web.py`
serves the archive read-only; there is no upload route.

A plain `POST` is the right shape, not a WebSocket:

- `transcribe()` takes a whole file, ffmpeg-decodes it in one pass, and runs a
  single MLX inference. There is no incremental decode to feed.
- Both ALENA callers already hold the complete recording before they ask for a
  transcript — the Telegram bot downloads the voice memo, and the browser
  buffers its chunks until the user stops speaking.

A persistent connection would only pay for itself with live partial
transcripts, which needs VAD plus sliding-window decoding on top of MLX. That
is a separate project, not a change of transport.

---

## Request

```
POST {WEB_HOST}:{WEB_PORT}/api/transcribe
Authorization: Bearer <shared secret>
Content-Type: multipart/form-data
```

| Field | Required | Meaning |
|---|---|---|
| `audio` | yes | The recording, in whatever container it arrived in |
| `language` | no | ISO code to force; absent means auto-detect |

Send the bytes unconverted. ffmpeg on the text-whisperer side decodes ogg/opus,
webm, m4a, wav and mp3 already, so ALENA does no audio processing — that is the
whole point of moving STT off it.

## Response

`200` with:

```json
{
  "text": "the transcript",
  "language": "en",
  "audio_seconds": 51.2,
  "elapsed_seconds": 0.9,
  "segments": [{ "start": 0.0, "end": 3.1, "text": "..." }]
}
```

The field names are exactly text-whisperer's own `Transcript` dataclass, so the
handler is a `dataclasses.asdict` away from done.

| Status | ALENA's behaviour |
|---|---|
| `200` | Use the transcript |
| `401` / `403` | Hard error naming the token as the likely cause |
| `503` | Treated as retryable: busy, or no model loaded |
| other `4xx`/`5xx` | Hard error, body echoed into the log |

`GET /api/status` already exists and is used as the health check.

---

## How the server side behaves

Both questions this document originally left open have been decided:

**It takes the Telegram worker's GPU lock.** Transcription is deliberately one
thread there, because the GPU is one resource. `Bot.transcribe_file` acquires
the same `_gpu_lock` that `Bot._process` now holds, so an upload waits rather
than halving the speed of a meeting already running. If it cannot get the GPU
within 30 seconds it returns `503` — better than a socket that dies waiting.

**Uploads are not archived.** The archive is a record of meetings; a
five-second "what's on my calendar" is noise in it. The spooled file is deleted
once the transcript is returned.

Authentication is `WEB_PASSWORD` presented as a bearer token, compared in
constant time by the same `auth.check_password` the browser login uses. It
works on every API route, which is what lets ALENA's health check call
`/api/status` with the same header.

Testing it by hand:

```bash
curl -s -X POST http://127.0.0.1:8090/api/transcribe \
  -H "Authorization: Bearer $WEB_PASSWORD" \
  -F audio=@memo.m4a -F language=en | jq .text
```

---

## Exposing it on the tailnet

`WEB_HOST` defaults to `127.0.0.1` and should stay there. Publish it with
`tailscale serve` instead of binding `0.0.0.0`:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8090
```

Then point ALENA at the tailnet name:

```dotenv
TEXT_WHISPERER_URL=https://macbook-pro-14-m4-pro.<tailnet>.ts.net
TEXT_WHISPERER_TOKEN=<the WEB_PASSWORD>
```

Set `WEB_PASSWORD` before doing this. Without it the archive — every transcript
ever made — is readable by anything on the tailnet.
