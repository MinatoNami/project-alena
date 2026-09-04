<script setup lang="ts">
const { get } = useAlena()
const clock = useClock()
// Not awaited. A top-level await here would put every watcher registered
// below it outside the component's setup scope, and `useAsyncData(..., {
// watch })` silently stops refetching -- which is how the filters break. The
// zone is a module-level ref, so formatting re-renders once it arrives.
clock.load()

type Event = {
  kind: string
  at: string
  repository_id: string
  summary: string
  detail: string | null
  adverse: boolean
  reference: Record<string, unknown>
}

const repository = ref('')
const kinds = ref<string[]>([])

const { data: repositories } = await useAsyncData('repos-for-history', () =>
  get<{ id: string; name: string }[]>('/api/repositories'),
)

const { data, refresh } = await useAsyncData(
  'history',
  () => {
    const params = new URLSearchParams({ limit: '200' })
    if (repository.value) params.set('repository_id', repository.value)
    if (kinds.value.length) params.set('kind', kinds.value.join(','))
    return get<{ events: Event[]; counts: Record<string, number>; kinds: string[] }>(
      `/api/history?${params}`,
    )
  },
  { watch: [repository, kinds] },
)

const filtered = computed(() => Boolean(repository.value) || kinds.value.length > 0)
const repositoryName = computed(
  () =>
    repositories.value?.find((r) => r.id === repository.value)?.name
    ?? 'any repository',
)

function clearFilters() {
  repository.value = ''
  kinds.value = []
}

function toggle(kind: string) {
  kinds.value = kinds.value.includes(kind)
    ? kinds.value.filter((k) => k !== kind)
    : [...kinds.value, kind]
}

/** Group by day, because "what happened on the 3rd" is how anyone reads this.
 *  Grouped on the *local* day: a run at 02:01 in Singapore is stored as the
 *  previous day in UTC, and filing it under yesterday would be wrong. */
const days = computed(() => {
  const grouped = new Map<string, Event[]>()
  for (const event of data.value?.events ?? []) {
    const day = clock.dayKey(event.at)
    grouped.set(day, [...(grouped.get(day) ?? []), event])
  }
  return [...grouped.entries()]
})

const kindClass = (kind: string) =>
  ({
    scan: 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300',
    research: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
    review: 'bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300',
    decision: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
    implementation: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  })[kind] ?? 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800'
</script>

<template>
  <div>
    <div class="mb-6 flex flex-wrap items-center gap-x-6 gap-y-3">
      <select
        v-model="repository"
        class="rounded border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
      >
        <option value="">All repositories</option>
        <option v-for="repo in repositories" :key="repo.id" :value="repo.id">{{ repo.name }}</option>
      </select>

      <div class="flex flex-wrap gap-2">
        <button
          v-for="kind in data?.kinds ?? []"
          :key="kind"
          class="rounded px-2 py-1 text-xs"
          :class="kinds.includes(kind) || !kinds.length
            ? kindClass(kind)
            : 'text-neutral-400 dark:text-neutral-600'"
          @click="toggle(kind)"
        >
          {{ kind }}
          <span v-if="data?.counts?.[kind]" class="ml-1 opacity-60">{{ data.counts[kind] }}</span>
        </button>
        <button
          v-if="kinds.length"
          class="text-xs text-neutral-500 underline"
          @click="kinds = []"
        >show all</button>
      </div>
    </div>

    <!-- Two different empty states. Saying "nothing has happened yet" when a
         filter simply matched nothing reads as the system being broken. -->
    <div v-if="!days.length && filtered" class="text-sm text-neutral-500">
      <p>No {{ kinds.length ? kinds.join(' or ') : 'events' }} for
        <span class="font-medium">{{ repositoryName }}</span>.</p>
      <button class="mt-2 text-xs underline" @click="clearFilters">Clear the filters</button>
    </div>
    <p v-else-if="!days.length" class="text-sm text-neutral-500">Nothing has happened yet.</p>
    <p v-else class="mb-4 text-xs text-neutral-500">Times in {{ clock.zoneLabel }}.</p>

    <section v-for="[day, events] in days" :key="day" class="mb-8">
      <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{{ day }}</h2>
      <ul class="divide-y divide-neutral-200 rounded border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
        <li v-for="(event, index) in events" :key="`${day}-${index}`" class="px-4 py-3">
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
            <span class="w-11 shrink-0 font-mono text-xs text-neutral-500">
              {{ clock.time(event.at) }}
            </span>
            <span class="rounded px-2 py-0.5 text-xs" :class="kindClass(event.kind)">
              {{ event.kind }}
            </span>
            <span class="text-xs text-neutral-500">{{ event.repository_id }}</span>
            <span :class="event.adverse ? 'text-amber-700 dark:text-amber-500' : ''">
              {{ event.summary }}
            </span>
          </div>
          <p
            v-if="event.detail"
            class="mt-1 pl-14 text-xs leading-relaxed text-neutral-500"
          >{{ event.detail }}</p>
        </li>
      </ul>
    </section>
  </div>
</template>
