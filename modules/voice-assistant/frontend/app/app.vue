<template>
  <div class="p-6">
    <NuxtRouteAnnouncer />

    <div class="max-w-xl space-y-4">
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

      <UButton
        :color="isRecording ? 'error' : 'primary'"
        :loading="status === 'connecting' || status === 'stopping'"
        :disabled="wsStatus !== 'connected'"
        @click="toggle"
      >
        {{ isRecording ? "Stop recording" : "Start recording" }}
      </UButton>

      <div class="text-sm">Recorder Status: {{ status }}</div>

      <div v-if="error" class="text-sm text-red-600">
        {{ error }}
      </div>

      <div v-if="lastMessage" class="mt-4 p-4 bg-gray-100 rounded">
        <div class="text-sm font-semibold mb-2">Last Message:</div>
        <pre class="text-xs overflow-auto">{{
          JSON.stringify(lastMessage, null, 2)
        }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
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

async function toggle() {
  if (isRecording.value) await stop();
  else await start();
}
</script>
