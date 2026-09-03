<script setup lang="ts">
const { get } = useAlena()
const { data, error } = await useAsyncData('repositories', () => get<any[]>('/api/repositories'))
</script>

<template>
  <div>
    <div v-if="error" class="text-sm text-red-700 dark:text-red-400">Cannot reach the API.</div>
    <ul v-else class="divide-y divide-neutral-200 rounded border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
      <li v-for="repo in data" :key="repo.id" class="px-4 py-3">
        <NuxtLink :to="`/repositories/${repo.id}`" class="text-sm font-medium hover:underline">
          {{ repo.name }}
        </NuxtLink>
        <p class="mt-1 text-xs text-neutral-500">
          {{ repo.file_count ?? '—' }} files ·
          {{ repo.languages?.slice(0, 4).join(', ') || 'not scanned' }}
          <span v-if="Object.entries(repo.capabilities || {}).some(([k, v]) => v && k !== 'research' && k !== 'analyze' && k !== 'plan')">
            · writable
          </span>
          <span v-else> · read-only</span>
        </p>
      </li>
    </ul>
  </div>
</template>
