<template>
  <div class="p-6">
    <NuxtRouteAnnouncer />

    <div class="max-w-xl space-y-4">
      <div class="text-sm text-gray-600">WebSocket: {{ wsUrl }}</div>

      <UButton
        :color="isRecording ? 'error' : 'primary'"
        :loading="status === 'connecting' || status === 'stopping'"
        @click="toggle"
      >
        {{ isRecording ? "Stop recording" : "Start recording" }}
      </UButton>

      <div class="text-sm">Status: {{ status }}</div>

      <div v-if="error" class="text-sm text-red-600">
        {{ error }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const { wsUrl, status, error, isRecording, start, stop } =
  useAudioStreamRecorder();

async function toggle() {
  if (isRecording.value) await stop();
  else await start();
}
</script>
