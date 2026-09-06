<script setup lang="ts">
const { get } = useAlena()
const { data, error, refresh, status } = await useAsyncData('status', () => get<Status>('/api/status'))

// Reading the pipeline is cheap and the numbers move when a scheduled job
// runs, so the page refreshes itself rather than going stale on a tab left
// open overnight.
onMounted(() => {
  const timer = setInterval(refresh, 30_000)
  onUnmounted(() => clearInterval(timer))
})
</script>

<template>
  <div>
    <div v-if="error" class="rounded border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950">
      <p class="font-medium">Cannot reach the API.</p>
      <p class="mt-1 text-neutral-600 dark:text-neutral-400">
        Start it with <code class="font-mono">scripts/start_alena_dashboard.sh</code>.
      </p>
    </div>

    <template v-else-if="data">
      <section class="mb-8 flex flex-wrap gap-x-10 gap-y-2 text-sm">
        <div>
          <span class="text-neutral-500">Repositories</span>
          <span class="ml-2 font-medium">{{ data.coverage.scanned }}/{{ data.coverage.repositories }} scanned</span>
        </div>
        <div>
          <span class="text-neutral-500">Last scan</span>
          <span class="ml-2 font-medium">
            {{ data.coverage.last_scan_days === null ? 'never' : `${data.coverage.last_scan_days}d ago` }}
          </span>
        </div>
        <div>
          <span class="text-neutral-500">Research</span>
          <span class="ml-2 font-medium">{{ data.coverage.research_documents }} document(s)</span>
        </div>
      </section>

      <section class="mb-8">
        <h2 class="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">Pipeline</h2>
        <details class="mb-3 rounded border border-neutral-200 dark:border-neutral-800">
          <summary class="cursor-pointer px-4 py-2 text-xs text-neutral-500">How a night runs</summary>
          <div class="border-t border-neutral-200 px-4 py-3 dark:border-neutral-800">
            <PipelineDiagram :stages="data.stages" />
          </div>
        </details>
        <ul class="divide-y divide-neutral-200 rounded border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          <li
            v-for="stage in data.stages"
            :key="stage.name"
            class="flex items-baseline justify-between px-4 py-3 text-sm"
          >
            <span :class="stage.stale ? 'text-amber-700 dark:text-amber-500' : ''">
              {{ stage.label }}
              <span v-if="stage.stale" class="ml-2 text-xs">stalled</span>
            </span>
            <span class="tabular-nums">
              <span :class="stage.count ? 'font-medium' : 'text-neutral-400'">{{ stage.count || 'none' }}</span>
              <span v-if="stage.oldest_days !== null && stage.count" class="ml-2 text-xs text-neutral-500">
                oldest {{ stage.oldest_days }}d
              </span>
            </span>
          </li>
        </ul>
      </section>

      <section v-if="data.jobs.length" class="mb-8">
        <h2 class="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">Scheduled</h2>
        <ul class="space-y-1 text-sm">
          <li
            v-for="job in data.jobs"
            :key="job.label"
            :class="job.failing ? 'text-red-700 dark:text-red-400' : 'text-neutral-600 dark:text-neutral-400'"
          >{{ job.description }}</li>
        </ul>
      </section>

      <section
        v-if="data.stranded.length"
        class="mb-8 rounded border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-900 dark:bg-amber-950"
      >
        <p class="font-medium">
          {{ data.stranded.length }} observation(s) have a failed review and will not be retried on their own.
        </p>
        <ul class="mt-2 space-y-1 text-neutral-700 dark:text-neutral-300">
          <li v-for="row in data.stranded" :key="row.title">{{ row.repository_id }} — {{ row.title }}</li>
        </ul>
        <p class="mt-2 font-mono text-xs">alena-improve review --all --retry-failed</p>
      </section>

      <div class="mb-8 border-t border-neutral-200 pt-6 dark:border-neutral-800">
        <RunPanel @finished="refresh" />
      </div>

      <p v-if="data.waiting_on_you" class="text-sm">
        <NuxtLink to="/queue" class="font-medium underline">
          {{ data.waiting_on_you }} recommendation(s) need a decision
        </NuxtLink>
      </p>
      <p v-else-if="!data.coverage.research_documents" class="text-sm text-neutral-500">
        Nothing needs you. The loop produces recommendations once research is ingested:
        <span class="font-mono text-xs">alena-improve ingest-research &lt;repository&gt; &lt;file.md&gt;</span>
      </p>
      <p v-else class="text-sm text-neutral-500">Nothing needs you.</p>
    </template>

    <p v-else-if="status === 'pending'" class="text-sm text-neutral-500">Loading…</p>
  </div>
</template>
