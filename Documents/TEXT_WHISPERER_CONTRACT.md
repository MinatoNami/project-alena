# text-whisperer transcription endpoint

ALENA no longer runs Whisper. It sends audio to
[text-whisperer](https://github.com/MinatoNami/text-whisperer) over the tailnet
and gets a transcript back.

**This endpoint does not exist yet.** ALENA's client
([`modules/stt/text_whisperer.py`](../modules/stt/text_whisperer.py)) is written
against the contract below; the matching route has to be added to
text-whisperer's `src/telegram_stt/web.py` before voice input works. Until then
the Telegram bot and the voice backend both report STT as unavailable and keep
serving text.

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

## Sketch for `web.py`

The existing `Gate` covers cookie logins for the browser. A machine client
wants a header instead, so authorise on either.

```python
def _bearer_ok(self) -> bool:
    token = self.gate.password          # reuse WEB_PASSWORD as the shared secret
    if not token:
        return True                     # no gate configured; loopback/tailnet only
    header = self.headers.get("Authorization", "")
    return header.startswith("Bearer ") and compare_digest(header[7:], token)
```

Then in `do_POST`, before the cookie check:

```python
if route == "/api/transcribe":
    if not self._bearer_ok():
        return self._fail(HTTPStatus.UNAUTHORIZED, "bad token")

    # Spool to a temp file: transcribe() takes a Path, and a long recording
    # should not be held in memory twice.
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(self._multipart_field("audio"))
        path = Path(tmp.name)
    try:
        result = transcribe(
            path,
            model=self.bot.config.whisper_model,
            language=... or self.bot.config.whisper_language,
            initial_prompt=self.bot.config.whisper_initial_prompt,
            max_seconds=self.bot.config.max_audio_seconds,
        )
        return self._json(dataclasses.asdict(result))
    except TranscriptionError as exc:
        return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
    finally:
        path.unlink(missing_ok=True)
```

Two things worth deciding over there rather than here:

1. **Serialise against the worker.** Transcription is deliberately one thread,
   because the GPU is one resource. This route should take the same lock the
   Telegram worker uses, or a long meeting arriving by Telegram and a voice
   memo arriving from ALENA will halve each other's speed.
2. **Whether these land in the archive.** A two-second "what's on my calendar"
   is noise in a list of meetings. Skipping `archive.store()` for this route is
   probably right; that is a product call.

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
