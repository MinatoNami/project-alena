<script setup lang="ts">
const { get } = useAlena()
const { data, error } = await useAsyncData('tools', () => get<any[]>('/api/tools'))

const healthClass = (h: string) =>
  h === 'contested'
    ? 'text-amber-700 dark:text-amber-500'
    : h === 'failing'
      ? 'text-red-700 dark:text-red-400'
      : h === 'unused'
        ? 'text-neutral-500'
        : 'text-neutral-700 dark:text-neutral-300'
</script>

<template>
  <div>
    <div v-if="error" class="text-sm text-red-700 dark:text-red-400">Cannot reach the API.</div>

    <template v-else-if="data">
      <p class="mb-4 text-xs text-neutral-500">
        From the gateway's audit log. <span class="font-medium">contested</span> is the one to watch: an agent
        repeatedly refused a capability means either the catalog is missing something, or the policy is wrong
        about who should have it. Token savings and accuracy are not measured — this is about use and
        reliability, not value.
      </p>
      <table class="w-full text-sm">
        <thead class="text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th class="py-2">Tool</th>
            <th>Health</th>
            <th class="text-right">Calls</th>
            <th class="text-right">Failed</th>
            <th class="text-right">Refused</th>
            <th class="text-right">Median</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-neutral-200 dark:divide-neutral-800">
          <tr v-for="row in data" :key="row.tool">
            <td class="py-2 font-mono text-xs">{{ row.tool }}</td>
            <td :class="healthClass(row.health)">{{ row.health }}</td>
            <td class="text-right tabular-nums">{{ row.invocations }}</td>
            <td class="text-right tabular-nums">{{ row.failures || '' }}</td>
            <td class="text-right tabular-nums">{{ row.denials || '' }}</td>
            <td class="text-right tabular-nums text-xs text-neutral-500">
              {{ row.median_ms === null ? '' : `${Math.round(row.median_ms)}ms` }}
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
