import { computed, onBeforeUnmount, onMounted, ref } from "vue";

type RecorderStatus =
  | "idle"
  | "connecting"
  | "recording"
  | "stopping"
  | "error";

type WebSocketStatus = "disconnected" | "connecting" | "connected" | "error";

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
  const wsStatus = ref<WebSocketStatus>("disconnected");
  const lastMessage = ref<any>(null);

  const isRecording = computed(
    () => status.value === "recording" || status.value === "connecting"
  );

  let mediaStream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let scriptProcessor: ScriptProcessorNode | null = null;
  let websocket: WebSocket | null = null;
  let reconnectTimeout: NodeJS.Timeout | null = null;
  let isClosing = false;

  function resetError() {
    error.value = null;
  }

  function stopTracks(stream: MediaStream | null) {
    stream?.getTracks().forEach((t) => t.stop());
  }

  function closeWebSocket() {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    try {
      if (websocket) {
        isClosing = true;
        websocket.close();
        websocket = null;
      }
    } catch {
      // ignore
    }
  }

  function connectWebSocket() {
    if (!process.client) return;
    if (websocket && websocket.readyState === WebSocket.OPEN) return;

    const url = wsUrl.value;
    if (!url) {
      error.value = "Missing WebSocket URL";
      wsStatus.value = "error";
      return;
    }

    wsStatus.value = "connecting";
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.addEventListener("open", () => {
      console.log("WebSocket connected");
      wsStatus.value = "connected";
      error.value = null;
      websocket = ws;
    });

    ws.addEventListener("message", (event) => {
      try {
        const data = JSON.parse(event.data);
        lastMessage.value = data;
        console.log("Received message:", data);
      } catch {
        // If it's not JSON, store as raw data
        lastMessage.value = event.data;
      }
    });

    ws.addEventListener("error", (err) => {
      console.error("WebSocket error:", err);
      wsStatus.value = "error";
      error.value = "WebSocket connection error";
    });

    ws.addEventListener("close", () => {
      console.log("WebSocket closed");
      wsStatus.value = "disconnected";
      websocket = null;

      // Auto-reconnect unless explicitly closing
      if (!isClosing) {
        console.log("Reconnecting in 3 seconds...");
        reconnectTimeout = setTimeout(() => {
          connectWebSocket();
        }, 3000);
      }
    });
  }

  async function start() {
    if (!process.client) return;
    if (isRecording.value) return;

    resetError();
    status.value = "connecting";

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("getUserMedia is not supported in this browser");
      }

      // Ensure WebSocket is connected
      if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        connectWebSocket();
        // Wait for connection
        await new Promise<void>((resolve, reject) => {
          const checkInterval = setInterval(() => {
            if (websocket && websocket.readyState === WebSocket.OPEN) {
              clearInterval(checkInterval);
              resolve();
            } else if (wsStatus.value === "error") {
              clearInterval(checkInterval);
              reject(new Error("WebSocket connection failed"));
            }
          }, 100);
          // Timeout after 10 seconds
          setTimeout(() => {
            clearInterval(checkInterval);
            reject(new Error("WebSocket connection timeout"));
          }, 10000);
        });
      }

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Use Web Audio API for raw PCM capture
      audioContext = new (window.AudioContext ||
        (window as any).webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(mediaStream);

      // Create script processor for raw PCM data
      // 4096 samples at 48kHz = ~85ms
      scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);

      scriptProcessor.onaudioprocess = (event: AudioProcessingEvent) => {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) return;

        const inputData = event.inputBuffer.getChannelData(0);

        // Convert float32 to PCM16
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7fff;
        }

        try {
          websocket.send(pcm16.buffer);
        } catch {
          // ignore per-chunk failures
        }
      };

      source.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);

      status.value = "recording";

      // Send start action to server
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        try {
          websocket.send(JSON.stringify({ action: "start" }));
        } catch {
          // ignore send failures
        }
      }
    } catch (e) {
      error.value =
        e instanceof Error ? e.message : "Failed to start recording";
      status.value = "error";

      if (audioContext) {
        try {
          audioContext.close();
        } catch {
          // ignore
        }
      }

      stopTracks(mediaStream);
      mediaStream = null;
      audioContext = null;
      scriptProcessor = null;

      // Don't close WebSocket anymore - keep it connected
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
      if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
      }

      if (audioContext) {
        audioContext.close();
        audioContext = null;
      }

      // Send end action to server
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        try {
          websocket.send(JSON.stringify({ action: "end" }));
        } catch {
          // ignore send failures
        }
      }
    } finally {
      stopTracks(mediaStream);
      mediaStream = null;

      // Don't close WebSocket - keep it connected

      status.value = "idle";
    }
  }

  onMounted(() => {
    // Connect WebSocket on mount
    connectWebSocket();
  });

  onBeforeUnmount(() => {
    // Stop recording and close WebSocket when component unmounts
    isClosing = true;
    void stop();
    closeWebSocket();
  });

  return {
    wsUrl,
    status,
    wsStatus,
    error,
    lastMessage,
    isRecording,
    start,
    stop,
  };
}
