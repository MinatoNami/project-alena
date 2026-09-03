<template>
  <UApp>
    <NuxtRouteAnnouncer />

    <UContainer class="py-6 space-y-6">
      <UCard>
        <template #header>
          <div class="text-base font-semibold">Voice (WebSocket)</div>
        </template>

        <div class="space-y-4">
          <div class="text-sm text-gray-600">WebSocket: {{ wsUrl }}</div>
          <div
            class="text-sm"
            :class="{
              'text-green-600': wsStatus === 'connected',
              'text-yellow-600': wsStatus === 'connecting',
              'text-red-600': wsStatus === 'error',
              'text-gray-600': wsStatus === 'disconnected',
            }"
          >
            WebSocket Status: {{ wsStatus }}
          </div>

          <div class="flex items-center gap-3">
            <UButton
              :color="isRecording ? 'error' : 'primary'"
              :loading="status === 'connecting' || status === 'stopping'"
              :disabled="wsStatus !== 'connected'"
              @click="toggle"
            >
              {{ isRecording ? "Stop recording" : "Start recording" }}
            </UButton>

            <div class="text-sm text-gray-600">Recorder: {{ status }}</div>
          </div>

          <div v-if="error" class="text-sm text-red-600">
            {{ error }}
          </div>

          <div v-if="lastMessage" class="rounded-lg border border-gray-200 p-4">
            <div class="text-sm font-semibold mb-2">Last Message</div>
            <pre
              class="text-xs overflow-auto whitespace-pre-wrap break-words"
              >{{ JSON.stringify(lastMessage, null, 2) }}</pre
            >
          </div>
        </div>
      </UCard>

      <UCard>
        <template #header>
          <div class="text-base font-semibold">Chat</div>
        </template>

        <div class="flex flex-col h-96">
          <div
            ref="chatScrollEl"
            class="flex-1 overflow-auto rounded-lg border border-gray-200 bg-white p-4"
          >
            <div v-if="messages.length === 0" class="text-sm text-gray-500">
              No messages yet.
            </div>

            <div v-else class="space-y-3">
              <div
                v-for="(m, idx) in messages"
                :key="idx"
                class="flex min-w-0"
                :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  class="max-w-xl rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words"
                  :class="
                    m.role === 'user'
                      ? 'bg-gray-900 text-white'
                      : 'bg-gray-100 text-gray-900'
                  "
                >
                  {{ m.content }}
                </div>
              </div>
            </div>
          </div>

          <div class="mt-4 space-y-2">
            <label for="chat-input" class="sr-only">Message</label>
            <UTextarea
              id="chat-input"
              v-model="draftMessage"
              :disabled="chatLoading"
              placeholder="Enter your message..."
              :rows="3"
              @keydown.ctrl.enter.prevent="sendMessage"
              @keydown.meta.enter.prevent="sendMessage"
            />

            <div class="flex items-center justify-between gap-3">
              <div class="text-xs text-gray-500">
                Use Ctrl+Enter (Cmd+Enter on Mac) to send
              </div>

              <UButton
                color="primary"
                :loading="chatLoading"
                :disabled="!draftMessage.trim() || chatLoading"
                @click="sendMessage"
              >
                Send
              </UButton>
            </div>

            <div
              v-if="chatError"
              class="rounded-lg border border-red-200 bg-red-50 p-4"
            >
              <div class="text-sm font-semibold text-red-900 mb-2">Error</div>
              <div class="text-sm text-red-800">{{ chatError }}</div>
            </div>
          </div>
        </div>
      </UCard>
    </UContainer>
  </UApp>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { useAudioStreamRecorder } from "../composables/useAudioStreamRecorder";

const {
  wsUrl,
  status,
  wsStatus,
  error,
  lastMessage,
  isRecording,
  start,
  stop,
} = useAudioStreamRecorder();

// Chat state
type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  createdAt: number;
};

const chatStorageKey = "voice-assistant.chat.messages";

const messages = ref<ChatMessage[]>([]);
const draftMessage = ref("");
const chatError = ref("");
const chatLoading = ref(false);
const config = useRuntimeConfig();
const llmApiUrl = (config.public as any).llmApiUrl;
const chatScrollEl = ref<HTMLElement | null>(null);

function persistMessages() {
  if (!import.meta.client) return;
  try {
    localStorage.setItem(chatStorageKey, JSON.stringify(messages.value));
  } catch {
    // ignore persistence errors (private mode, storage full, etc.)
  }
}

function restoreMessages() {
  if (!import.meta.client) return;
  try {
    const raw = localStorage.getItem(chatStorageKey);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return;

    messages.value = parsed
      .filter((m) => m && (m.role === "user" || m.role === "assistant"))
      .map((m) => ({
        role: m.role,
        content: typeof m.content === "string" ? m.content : "",
        createdAt: typeof m.createdAt === "number" ? m.createdAt : Date.now(),
      }));
  } catch {
    // ignore parse errors
  }
}

async function scrollToBottom() {
  await nextTick();
  const el = chatScrollEl.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

onMounted(async () => {
  restoreMessages();
  await scrollToBottom();
});

watch(
  messages,
  async () => {
    persistMessages();
    await scrollToBottom();
  },
  { deep: true }
);

// Reasoning models (qwen3, deepseek-r1, ...) stream a <think> scratchpad ahead
// of the answer. It arrives token by token, so whether we are inside one has to
// be remembered between chunks rather than regexed out of a finished string.
const OPEN_TAGS = ["<think>", "<thinking>", "<reasoning>"];
const CLOSE_TAGS = ["</think>", "</thinking>", "</reasoning>"];

function earliestTag(text: string, tags: string[]): [number, string] {
  let at = -1;
  let found = "";
  for (const tag of tags) {
    const i = text.indexOf(tag);
    if (i !== -1 && (at === -1 || i < at)) {
      at = i;
      found = tag;
    }
  }
  return [at, found];
}

function createReasoningFilter() {
  let inReasoning = false;
  return {
    feed(delta: string): string {
      let kept = "";
      let remaining = delta;

      while (remaining) {
        const [at, tag] = earliestTag(
          remaining,
          inReasoning ? CLOSE_TAGS : OPEN_TAGS
        );
        if (at === -1) {
          if (!inReasoning) kept += remaining;
          break;
        }
        if (!inReasoning) kept += remaining.slice(0, at);
        remaining = remaining.slice(at + tag.length);
        inReasoning = !inReasoning;
      }
      return kept;
    },
  };
}

function stripReasoning(text: string): string {
  return createReasoningFilter().feed(text).trim();
}

async function sendMessage() {
  if (!draftMessage.value.trim() || chatLoading.value) return;

  chatLoading.value = true;
  chatError.value = "";
  const message = draftMessage.value.trim();

  messages.value.push({
    role: "user",
    content: message,
    createdAt: Date.now(),
  });
  const assistantMessage: ChatMessage = {
    role: "assistant",
    content: "",
    createdAt: Date.now(),
  };
  messages.value.push(assistantMessage);
  draftMessage.value = "";
  await scrollToBottom();

  try {
    const response = await fetch(`${llmApiUrl}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        // No model: the backend substitutes whichever one LM Studio has
        // loaded, so a name cached in this page cannot go stale.
        messages: messages.value.map((m) => ({
          role: m.role,
          content: m.content,
        })),
        stream: true,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      const data = await response.json();
      const content = data?.choices?.[0]?.message?.content;
      if (typeof content === "string") {
        assistantMessage.content = stripReasoning(content);
      }
    } else {
      const decoder = new TextDecoder();
      const reasoning = createReasoningFilter();
      let carry = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        carry += decoder.decode(value, { stream: true });
        const lines = carry.split("\n");
        carry = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;

          const body = trimmed.slice(5).trim();
          if (!body || body === "[DONE]") continue;

          try {
            const data = JSON.parse(body);
            const delta = data?.choices?.[0]?.delta?.content;
            if (typeof delta === "string") {
              assistantMessage.content += reasoning.feed(delta);
            }
          } catch {
            // Skip frames that aren't valid JSON
          }
        }
      }
    }
    chatLoading.value = false;
  } catch (e) {
    chatError.value = `Error: ${e instanceof Error ? e.message : String(e)}`;
    chatLoading.value = false;
    console.error("Chat error:", e);
  }
}

async function toggle() {
  if (isRecording.value) await stop();
  else await start();
}
</script>
