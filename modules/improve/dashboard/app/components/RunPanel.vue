<script setup lang="ts">
const { get, post } = useAlena()

type Command = {
  key: string
  label: string
  description: string
  costs: string | null
  parameters: string[]
  writes: boolean
}
type Run = {
  id: string
  command: string
  label: string
  state: 'running' | 'finished' | 'failed'
  exit_code: number | null
  started_at: string
  finished_at: string | null
  output?: string[]
}

const emit = defineEmits<{ finished: [] }>()

// Commands that act on the whole portfolio. `implement` takes a specific
// recommendation, so it belongs on that recommendation, not in a row of
// buttons where a stray click reaches it.
const { data: all } = await useAsyncData('commands', () => get<Command[]>('/api/commands'))
const commands = computed(() => (all.value ?? []).filter((c) => !c.parameters.length))
const runs = ref<Run[]>([])
const current = ref<Run | null>(null)
const active = ref<Run | null>(null)
const failure = ref<string | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  const body = await get<{ current: Run | null; runs: Run[] }>('/api/runs')
  current.value = body.current
  runs.value = body.runs
  if (active.value) {
    const detail = await get<Run>(`/api/runs/${active.value.id}`)
    const wasRunning = active.value.state === 'running'
    active.value = detail
    // The pipeline numbers only change once the work is done, so the page
    // behind this refreshes on the transition rather than on every poll.
    if (wasRunning && detail.state !== 'running') emit('finished')
  }
  if (!current.value && timer) {
    clearInterval(timer)
    timer = null
  }
}

function poll() {
  if (!timer) timer = setInterval(refresh, 2000)
}

async function start(key: string) {
  failure.value = null
  try {
    active.value = await post<Run>('/api/runs', { command: key })
    poll()
  } catch (e: any) {
    // 409 is the interesting one: something is already running. Nothing is
    // broken, so it reads as information rather than an error.
    failure.value = e?.data?.detail ?? e?.message ?? 'Could not start.'
  }
}

onMounted(() => {
  refresh()
  if (current.value) poll()
})
onUnmounted(() => timer && clearInterval(timer))

const busy = computed(() => Boolean(current.value))
</script>

<template>
  <section>
    <h2 class="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">Run a step</h2>

    <div class="flex flex-wrap gap-2">
      <button
        v-for="command in commands"
        :key="command.key"
        class="rounded border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-neutral-700"
        :disabled="busy"
        :title="command.description + (command.costs ? ` — costs ${command.costs}` : '')"
        @click="start(command.key)"
      >
        {{ command.label }}
        <span v-if="command.costs" class="ml-1 text-xs text-amber-700 dark:text-amber-500">$</span>
      </button>
    </div>

    <p class="mt-2 text-xs text-neutral-500">
      One at a time — they share a database and the same workspaces.
      <span class="text-amber-700 dark:text-amber-500">$</span> spends beyond local compute.
      Implementing is not here: it writes to a repository and stays a command you watch.
    </p>

    <p
      v-if="failure"
      class="mt-3 rounded border border-neutral-300 bg-neutral-100 p-3 text-sm dark:border-neutral-700 dark:bg-neutral-900"
    >{{ failure }}</p>

    <div v-if="active" class="mt-4 rounded border border-neutral-200 dark:border-neutral-800">
      <div class="flex items-baseline justify-between border-b border-neutral-200 px-4 py-2 text-sm dark:border-neutral-800">
        <span class="font-medium">{{ active.label }}</span>
        <span
          class="text-xs"
          :class="{
            'text-neutral-500': active.state === 'running',
            'text-emerald-700 dark:text-emerald-500': active.state === 'finished',
            'text-red-700 dark:text-red-400': active.state === 'failed',
          }"
        >
          {{ active.state === 'running' ? 'running…' : active.state }}
          <span v-if="active.exit_code">(exit {{ active.exit_code }})</span>
        </span>
      </div>
      <pre
        v-if="active.output?.length"
        class="max-h-64 overflow-auto px-4 py-3 font-mono text-xs leading-relaxed text-neutral-700 dark:text-neutral-300"
      >{{ active.output.join('\n') }}</pre>
      <p v-else class="px-4 py-3 text-xs text-neutral-500">No output yet.</p>
    </div>

    <div v-if="runs.length > 1" class="mt-4">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Recent</h3>
      <ul class="mt-2 space-y-1 text-xs">
        <li v-for="run in runs.slice(0, 6)" :key="run.id" class="flex gap-3 text-neutral-500">
          <button class="underline" @click="active = run; refresh()">{{ run.label }}</button>
          <span :class="run.state === 'failed' ? 'text-red-700 dark:text-red-400' : ''">{{ run.state }}</span>
          <span>{{ run.started_at.slice(11, 16) }}</span>
        </li>
      </ul>
      <p class="mt-2 text-xs text-neutral-500">
        Started from here only — the scheduled jobs run the same commands and do not appear.
      </p>
    </div>
  </section>
</template>
