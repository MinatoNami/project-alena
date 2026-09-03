<script setup lang="ts">
const { get, post } = useAlena()
const { data, error, refresh } = await useAsyncData('queue', () => get<Recommendation[]>('/api/queue'))

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

    <div v-else-if="!data?.length" class="text-sm text-neutral-500">Nothing is awaiting a decision.</div>

    <div v-else class="space-y-6">
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
