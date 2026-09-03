<script setup lang="ts">
const { get, post } = useAlena()
const { data, error, refresh } = await useAsyncData('queue', () => get<Recommendation[]>('/api/queue'))

type Run = { id: string; state: string; exit_code: number | null; output?: string[] }

// Accepted but not yet implemented. Fetched per repository because the queue
// endpoint is only what awaits a decision.
const { data: repositories } = await useAsyncData('repos-for-accepted', () =>
  get<{ id: string; name: string; capabilities: Record<string, boolean> }[]>('/api/repositories'),
)
const { data: acceptedRows, refresh: refreshAccepted } = await useAsyncData('accepted', async () => {
  const out: (Recommendation & { writable: boolean })[] = []
  for (const repo of repositories.value ?? []) {
    const rows = await get<Recommendation[]>(
      `/api/repositories/${repo.id}/recommendations?status=accepted`,
    )
    for (const row of rows) {
      out.push({ ...row, repository_name: repo.name, writable: Boolean(repo.capabilities?.modify) })
    }
  }
  return out
})

const confirming = ref<number | null>(null)
const implementing = ref<Run | null>(null)
const implementFailure = ref<string | null>(null)
let implementTimer: ReturnType<typeof setInterval> | null = null

async function implement(row: Recommendation) {
  implementFailure.value = null
  confirming.value = null
  try {
    implementing.value = await post<Run>('/api/runs', {
      command: 'implement',
      repository_id: row.repository_id,
      recommendation_id: row.id,
    })
    implementTimer = setInterval(async () => {
      const detail = await get<Run>(`/api/runs/${implementing.value!.id}`)
      implementing.value = detail
      if (detail.state !== 'running') {
        clearInterval(implementTimer!)
        implementTimer = null
        await refreshAccepted()
      }
    }, 2000)
  } catch (e: any) {
    implementFailure.value = e?.data?.detail ?? e?.message ?? 'Could not start.'
  }
}

onUnmounted(() => implementTimer && clearInterval(implementTimer))

const expanded = ref<number | null>(null)
const rejecting = ref<number | null>(null)
const reason = ref('')
const busy = ref<number | null>(null)
const failure = ref<string | null>(null)
const accepted = ref<{ id: number; next: string } | null>(null)

async function send(id: number, decision: string, why?: string) {
  busy.value = id
  failure.value = null
  try {
    const result = await post<{ to_status: string; next?: string }>(
      `/api/recommendations/${id}/decision`,
      { decision, reason: why },
    )
    if (result.next) accepted.value = { id, next: result.next }
    rejecting.value = null
    reason.value = ''
    await refresh()
  } catch (e: any) {
    // The state machine's refusals are the useful ones -- a rejection with no
    // reason, an illegal transition. Show what it said rather than "failed".
    failure.value = e?.data?.detail ?? e?.message ?? 'The request failed.'
  } finally {
    busy.value = null
  }
}

/**
 * The body is markdown rendered for a file. Shown as text here, its emphasis
 * markers leak through as a literal `**Verdict:**`, so they are stripped
 * rather than pulling in a markdown renderer for four asterisks.
 */
function plain(text: string) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|\s)_(.+?)_(?=\s|$|[.,])/g, '$1$2')
}

/** The sections of a rendered recommendation that carry a judgement. */
function sections(body: string | null) {
  if (!body) return []
  const wanted = ['Research Evidence', 'Codex Assessment', 'Claude Assessment', 'Disagreement']
  const found: { name: string; text: string }[] = []
  let current: string | null = null
  let buffer: string[] = []
  for (const line of body.split('\n')) {
    if (line.startsWith('### ')) {
      if (current && wanted.includes(current)) found.push({ name: current, text: plain(buffer.join('\n').trim()) })
      current = line.slice(4).trim()
      buffer = []
    } else if (current) buffer.push(line)
  }
  if (current && wanted.includes(current)) found.push({ name: current, text: plain(buffer.join('\n').trim()) })
  return found.filter((s) => s.text)
}

const priorityClass = (p?: string) =>
  p === 'HIGH'
    ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
    : p === 'MEDIUM'
      ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
      : 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300'
</script>

<template>
  <div>
    <div v-if="error" class="rounded border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950">
      Cannot reach the API.
    </div>

    <section v-if="acceptedRows?.length" class="mb-10">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        Accepted, awaiting implementation
      </h2>
      <p class="mt-1 text-xs text-neutral-500">
        Implementing creates a branch, has Codex make the change, runs the tests and has the diff
        independently reviewed. Nothing is pushed and nothing is merged.
      </p>

      <p
        v-if="implementFailure"
        class="mt-3 rounded border border-neutral-300 bg-neutral-100 p-3 text-sm dark:border-neutral-700 dark:bg-neutral-900"
      >{{ implementFailure }}</p>

      <ul class="mt-3 space-y-3">
        <li
          v-for="row in acceptedRows"
          :key="row.id"
          class="rounded border border-neutral-200 px-4 py-3 dark:border-neutral-800"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="text-sm">{{ row.title }}</span>
            <span class="text-xs text-neutral-500">{{ row.repository_name }}</span>
          </div>

          <p v-if="!row.writable" class="mt-2 text-xs text-neutral-500">
            {{ row.repository_id }} is read-only. Enable <code class="font-mono">modify</code> and
            <code class="font-mono">create_branch</code> for it in
            <code class="font-mono">config/repositories.yaml</code> first — nothing here can.
          </p>

          <div v-else class="mt-3">
            <button
              v-if="confirming !== row.id"
              class="rounded border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-neutral-700"
              :disabled="implementing?.state === 'running'"
              @click="confirming = row.id"
            >Implement…</button>

            <div v-else class="flex flex-wrap items-center gap-3">
              <span class="text-xs text-amber-700 dark:text-amber-500">
                This writes a branch to {{ row.repository_id }} and spends a Codex session.
              </span>
              <button
                class="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white dark:bg-neutral-100 dark:text-neutral-900"
                @click="implement(row)"
              >Yes, implement</button>
              <button class="text-xs text-neutral-500 underline" @click="confirming = null">Cancel</button>
            </div>
          </div>
        </li>
      </ul>

      <div v-if="implementing" class="mt-4 rounded border border-neutral-200 dark:border-neutral-800">
        <div class="flex items-baseline justify-between border-b border-neutral-200 px-4 py-2 text-sm dark:border-neutral-800">
          <span class="font-medium">Implementing</span>
          <span
            class="text-xs"
            :class="{
              'text-neutral-500': implementing.state === 'running',
              'text-emerald-700 dark:text-emerald-500': implementing.state === 'finished',
              'text-red-700 dark:text-red-400': implementing.state === 'failed',
            }"
          >{{ implementing.state === 'running' ? 'running… this takes a few minutes' : implementing.state }}</span>
        </div>
        <pre
          v-if="implementing.output?.length"
          class="max-h-64 overflow-auto px-4 py-3 font-mono text-xs leading-relaxed text-neutral-700 dark:text-neutral-300"
        >{{ implementing.output.join('\n') }}</pre>
        <p v-else class="px-4 py-3 text-xs text-neutral-500">No output yet.</p>
      </div>
    </section>

    <div v-if="!data?.length && !acceptedRows?.length" class="text-sm text-neutral-500">
      Nothing is awaiting a decision.
    </div>

    <div v-if="data?.length" class="space-y-6">
      <p v-if="failure" class="rounded border border-red-300 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950">
        {{ failure }}
      </p>

      <p
        v-if="accepted"
        class="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm dark:border-emerald-900 dark:bg-emerald-950"
      >
        Accepted. Implementing writes to the repository and takes a few minutes, so it stays a command you watch:
        <span class="mt-1 block font-mono text-xs">{{ accepted.next }}</span>
      </p>

      <article
        v-for="row in data"
        :key="row.id"
        class="rounded border border-neutral-200 p-5 dark:border-neutral-800"
      >
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span
            class="rounded px-2 py-0.5 text-xs font-medium"
            :class="priorityClass(row.breakdown?.priority)"
          >{{ row.breakdown?.priority ?? '?' }}</span>
          <h2 class="text-base font-medium">{{ row.title }}</h2>
        </div>
        <p class="mt-1 text-xs text-neutral-500">
          {{ row.repository_name ?? row.repository_id }} ·
          score {{ row.score?.toFixed(2) ?? '?' }} ·
          effort {{ row.estimated_effort ?? '?' }} ·
          confidence {{ row.confidence === null ? 'unknown' : `${Math.round(row.confidence * 100)}%` }}
        </p>

        <div class="mt-4 space-y-3">
          <section v-for="s in sections(row.body)" :key="s.name">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">{{ s.name }}</h3>
            <p
              class="mt-1 whitespace-pre-wrap text-sm text-neutral-700 dark:text-neutral-300"
              :class="expanded === row.id ? '' : 'line-clamp-4'"
            >{{ s.text }}</p>
          </section>
        </div>

        <button
          class="mt-3 text-xs text-neutral-500 underline"
          @click="expanded = expanded === row.id ? null : row.id"
        >{{ expanded === row.id ? 'Show less' : 'Read in full' }}</button>

        <div class="mt-5 flex flex-wrap items-center gap-3">
          <button
            class="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
            :disabled="busy === row.id"
            @click="send(row.id, 'accept')"
          >Accept</button>
          <button
            class="rounded border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-neutral-700"
            :disabled="busy === row.id"
            @click="rejecting = rejecting === row.id ? null : row.id"
          >Reject</button>
        </div>

        <div v-if="rejecting === row.id" class="mt-3">
          <label class="text-xs text-neutral-500">
            A reason is required. It goes into the context package and the next reviewer's prompt — without one
            the same idea comes back with nothing to recognise it by.
          </label>
          <div class="mt-2 flex gap-2">
            <input
              v-model="reason"
              class="flex-1 rounded border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
              placeholder="too much complexity for current product maturity"
              @keyup.enter="reason.trim() && send(row.id, 'reject', reason)"
            >
            <button
              class="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-40 dark:bg-neutral-100 dark:text-neutral-900"
              :disabled="!reason.trim() || busy === row.id"
              @click="send(row.id, 'reject', reason)"
            >Record</button>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
