import { computed, onBeforeUnmount, ref } from "vue";

type RecorderStatus =
  | "idle"
  | "connecting"
  | "recording"
  | "stopping"
  | "error";

export function useAudioStreamRecorder(options?: {
  wsUrl?: string;
  timesliceMs?: number;
}) {
  const runtimeConfig = useRuntimeConfig();
  const wsUrl = computed(
    () => options?.wsUrl ?? (runtimeConfig.public.wsAudioUrl as string)
  );
  const timesliceMs = computed(() => options?.timesliceMs ?? 250);

  const status = ref<RecorderStatus>("idle");
  const error = ref<string | null>(null);

  const isRecording = computed(
    () => status.value === "recording" || status.value === "connecting"
  );

  let mediaStream: MediaStream | null = null;
  let mediaRecorder: MediaRecorder | null = null;
  let websocket: WebSocket | null = null;

  function resetError() {
    error.value = null;
  }

  function pickMimeType(): string | undefined {
    if (!process.client) return undefined;
    if (typeof MediaRecorder === "undefined") return undefined;
    if (typeof MediaRecorder.isTypeSupported !== "function") return undefined;

    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
    ];

    return candidates.find((type) => MediaRecorder.isTypeSupported(type));
  }

  function stopTracks(stream: MediaStream | null) {
    stream?.getTracks().forEach((t) => t.stop());
  }

  function closeWebSocket(ws: WebSocket | null) {
    try {
      ws?.close();
    } catch {
      // ignore
    }
  }

  async function openWebSocket(url: string): Promise<WebSocket> {
    return await new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      const onOpen = () => {
        cleanup();
        resolve(ws);
      };
      const onError = () => {
        cleanup();
        reject(new Error("WebSocket connection failed"));
      };

      const cleanup = () => {
        ws.removeEventListener("open", onOpen);
        ws.removeEventListener("error", onError);
      };

      ws.addEventListener("open", onOpen);
      ws.addEventListener("error", onError);
    });
  }

  async function start() {
    if (!process.client) return;
    if (isRecording.value) return;

    resetError();
    status.value = "connecting";

    try {
      const url = wsUrl.value;
      if (!url) throw new Error("Missing WebSocket URL");

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("getUserMedia is not supported in this browser");
      }
      if (typeof MediaRecorder === "undefined") {
        throw new Error("MediaRecorder is not supported in this browser");
      }

      websocket = await openWebSocket(url);

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const mimeType = pickMimeType();
      mediaRecorder = mimeType
        ? new MediaRecorder(mediaStream, { mimeType })
        : new MediaRecorder(mediaStream);

      mediaRecorder.addEventListener("dataavailable", async (ev: BlobEvent) => {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) return;
        if (!ev.data || ev.data.size === 0) return;

        try {
          const buf = await ev.data.arrayBuffer();
          websocket.send(buf);
        } catch {
          // ignore per-chunk failures
        }
      });

      mediaRecorder.addEventListener("error", () => {
        error.value = "Audio recorder error";
        status.value = "error";
      });

      mediaRecorder.addEventListener("stop", () => {
        // Best-effort cleanup is handled by stop()
      });

      mediaRecorder.start(timesliceMs.value);
      status.value = "recording";
    } catch (e) {
      error.value =
        e instanceof Error ? e.message : "Failed to start recording";
      status.value = "error";

      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        try {
          mediaRecorder.stop();
        } catch {
          // ignore
        }
      }

      stopTracks(mediaStream);
      mediaStream = null;
      mediaRecorder = null;

      closeWebSocket(websocket);
      websocket = null;
    }
  }

  async function stop() {
    if (!process.client) return;
    if (!isRecording.value) {
      status.value = "idle";
      return;
    }

    status.value = "stopping";

    try {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        await new Promise<void>((resolve) => {
          const onStop = () => {
            mediaRecorder?.removeEventListener("stop", onStop);
            resolve();
          };
          mediaRecorder?.addEventListener("stop", onStop);
          try {
            mediaRecorder?.stop();
          } catch {
            resolve();
          }
        });
      }
    } finally {
      stopTracks(mediaStream);
      mediaStream = null;
      mediaRecorder = null;

      closeWebSocket(websocket);
      websocket = null;

      status.value = "idle";
    }
  }

  onBeforeUnmount(() => {
    // If the component using this composable unmounts, stop everything.
    void stop();
  });

  return {
    wsUrl,
    status,
    error,
    isRecording,
    start,
    stop,
  };
}
