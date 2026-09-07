<script setup lang="ts">
// One row per repository, holding what previously took four pages to gather:
// scan freshness from Repositories, observation counts from Research, decision
// state from Queue, activity from History.
//
// The three columns on the right had no page at all. A reviewer disagreement
// was recorded and then invisible, which defeats the point of recording it; a
// citation that cannot resolve was found at ingest and mentioned in a log; an
// errored review was counted in aggregate and never attributed. Anything that
// is not zero is meant to catch the eye, and anything that is zero is meant to
// disappear.

type Row = {
  id: string
  name: string
  enabled: boolean
  scanned_at: string | null
  head_sha: string
  file_count: number | null
  todos: number
  dependencies: number
  languages: string[]
  counts: {
    observations: number
    unreviewed: number
    research: number
    errored_reviews: number
  }
  recommendations: Record<string, number>
  awaiting_decision: number
  disagreements: { id: number; title: string; verdicts: string }[]
  unverifiable: { id: number; title: string; citations: string[] }[]
}

const { get } = useAlena()
const clock = useClock()
clock.load()

const { data, error, status, refresh } = await useAsyncData('overview', () =>
  get<{ repositories: Row[]; totals: Record<string, number> }>('/api/overview'),
)

const search = ref('')
const onlyAttention = ref(false)
const issueCount = (row: Row) => row.disagreements.length + row.unverifiable.length + row.counts.errored_reviews
const rows = computed(() => (data.value?.repositories ?? [])
  .filter(row => `${row.name} ${row.id}`.toLowerCase().includes(search.value.toLowerCase()))
  .filter(row => !onlyAttention.value || issueCount(row) > 0 || row.awaiting_decision > 0)
  .sort((a, b) => issueCount(b) - issueCount(a) || b.awaiting_decision - a.awaiting_decision || a.name.localeCompare(b.name)))
const totals = computed(() => data.value?.totals ?? {})

// Ordered so the states a person acts on come first, and terminal ones last.
const STATUS_ORDER = [
  'recommended',
  'accepted',
  'implemented',
  'successful',
  'unsuccessful',
  'rejected',
  'abandoned',
]

function statuses(row: Row) {
  return STATUS_ORDER.filter((s) => row.recommendations[s]).map((s) => ({
    status: s,
    count: row.recommendations[s],
  }))
}

function scanAge(row: Row): string {
  if (!row.scanned_at) return 'never'
  const days = Math.floor(
    (Date.now() - new Date(row.scanned_at).getTime()) / 86_400_000,
  )
  return Number.isNaN(days) ? 'unknown' : days <= 0 ? 'less than 1d' : `${days}d ago`
}

</script>

<template>
  <section class="panel repository-panel">
    <div class="panel-heading"><div><h2>Repository signals <span class="count-label">{{ data?.repositories.length ?? '—' }}</span></h2><p>Coverage, work in progress and review quality</p></div><NuxtLink to="/repositories" class="text-link">All repositories →</NuxtLink></div>
    <div class="repository-filters"><input v-model="search" type="search" aria-label="Search repositories" placeholder="Search repositories…" class="search-input"><label class="live-control"><input v-model="onlyAttention" type="checkbox"> Needs attention</label><span class="muted text-xs">{{ rows.length }} shown · priority first</span></div>
    <div v-if="error" class="empty-state" role="alert">Repository signals unavailable. <button class="text-link" @click="refresh()">Retry →</button></div>
    <p v-else-if="status === 'pending' && !data" class="empty-state">Loading repositories…</p>
    <p v-else-if="!rows.length" class="empty-state">{{ search || onlyAttention ? 'No repositories match these filters.' : 'No repositories registered yet.' }} <button v-if="search || onlyAttention" class="text-link" @click="search = ''; onlyAttention = false">Clear filters</button></p>
    <div v-if="!error && rows.length" class="overflow-x-auto rounded border border-neutral-200 dark:border-neutral-800">
      <table class="w-full text-sm repository-table">
        <thead class="text-xs uppercase tracking-wide text-neutral-500">
          <tr class="border-b border-neutral-200 dark:border-neutral-800">
            <th class="px-4 py-2 text-left font-medium">Repository</th>
            <th class="px-3 py-2 text-right font-medium">Scanned</th>
            <th class="px-3 py-2 text-right font-medium">Files</th>
            <th class="px-3 py-2 text-right font-medium">TODOs</th>
            <th class="px-3 py-2 text-right font-medium">Research</th>
            <th class="px-3 py-2 text-right font-medium">Observations</th>
            <th class="px-4 py-2 text-left font-medium">Recommendations</th>
            <th class="px-3 py-2 text-right font-medium">Quality signals</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-neutral-200 dark:divide-neutral-800">
          <tr v-for="row in rows" :key="row.id" class="align-top">
            <td class="px-4 py-3">
              <NuxtLink :to="`/repositories/${row.id}`" class="font-medium hover:underline">
                {{ row.name }}
              </NuxtLink>
              <div class="text-xs text-neutral-500">
                {{ row.id }}
                <span v-if="!row.enabled" class="ml-1 text-amber-700 dark:text-amber-500">disabled</span>
              </div>
            </td>
            <td class="px-3 py-3 text-right tabular-nums">
              {{ scanAge(row) }}
              <div v-if="row.head_sha" class="text-xs text-neutral-500">{{ row.head_sha }}</div>
            </td>
            <td class="px-3 py-3 text-right tabular-nums">{{ row.file_count ?? '—' }}</td>
            <td class="px-3 py-3 text-right tabular-nums">{{ row.todos || '—' }}</td>
            <td class="px-3 py-3 text-right tabular-nums">{{ row.counts.research || '—' }}</td>
            <td class="px-3 py-3 text-right tabular-nums">
              {{ row.counts.observations || '—' }}
              <div v-if="row.counts.unreviewed" class="text-xs text-amber-700 dark:text-amber-500">
                {{ row.counts.unreviewed }} unreviewed
              </div>
            </td>
            <td class="px-4 py-3">
              <span v-if="!statuses(row).length" class="text-neutral-400">none</span>
              <span
                v-for="entry in statuses(row)"
                :key="entry.status"
                class="mr-2 inline-block whitespace-nowrap text-xs"
                :class="entry.status === 'recommended'
                  ? 'font-medium text-amber-700 dark:text-amber-500'
                  : 'text-neutral-500'"
              >{{ entry.count }} {{ entry.status }}</span>
            </td>
            <td class="px-3 py-3 text-right text-xs">
              <div v-if="row.disagreements.length" class="text-amber-700 dark:text-amber-500">
                {{ row.disagreements.length }} disagreement{{ row.disagreements.length === 1 ? '' : 's' }}
              </div>
              <div v-if="row.unverifiable.length" class="text-amber-700 dark:text-amber-500">
                {{ row.unverifiable.length }} unverifiable citation{{ row.unverifiable.length === 1 ? '' : 's' }}
              </div>
              <div v-if="row.counts.errored_reviews" class="text-neutral-500">
                {{ row.counts.errored_reviews }} errored review{{ row.counts.errored_reviews === 1 ? '' : 's' }}
              </div>
              <span
                v-if="!row.disagreements.length && !row.unverifiable.length && !row.counts.errored_reviews"
                class="text-neutral-400"
              >—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- The detail behind the right-hand column. Two reviewers reaching
         opposite conclusions is the single most interesting thing this system
         produces, and it was previously only visible in the database. -->
    <details v-if="totals.disagreements" class="mt-3 rounded border border-neutral-200 dark:border-neutral-800">
      <summary class="cursor-pointer px-4 py-2 text-xs text-neutral-500">
        Where the reviewers disagreed
      </summary>
      <ul class="divide-y divide-neutral-200 border-t border-neutral-200 text-sm dark:divide-neutral-800 dark:border-neutral-800">
        <li v-for="row in rows" :key="row.id">
          <div v-for="item in row.disagreements" :key="item.id" class="px-4 py-3">
            <div>{{ item.title }}</div>
            <div class="text-xs text-neutral-500">
              {{ row.id }} · {{ item.verdicts.split(',').join('  ·  ') }}
            </div>
          </div>
        </li>
      </ul>
    </details>
  </section>
</template>
