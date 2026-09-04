<script setup lang="ts">
const { get } = useAlena()
const clock = useClock()
clock.load()

type Summary = {
  id: number
  repository_id: string
  created_at: string
  source: string
  title: string | null
  document_date: string | null
  path: string | null
  size: number
  observation_count: number
}

type Document = Summary & {
  content: string
  observations: { id: number; title: string; duplicate_reason: string | null }[]
}

const { data: documents } = await useAsyncData('research', () =>
  get<Summary[]>('/api/research'),
)

const open = ref<number | null>(null)
const loaded = ref<Record<number, Document>>({})

async function expand(id: number) {
  open.value = open.value === id ? null : id
  if (open.value && !loaded.value[id]) {
    loaded.value = { ...loaded.value, [id]: await get<Document>(`/api/research/${id}`) }
  }
}

const sourceClass = (source: string) =>
  source === 'operator'
    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
    : 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300'
</script>

<template>
  <div>
    <p v-if="!documents?.length" class="text-sm text-neutral-500">
      No research on record. Drop a markdown file in
      <code class="font-mono text-xs">~/alena-research/&lt;repository&gt;/</code> and run a cycle, or
      write one on the <NuxtLink to="/propose" class="underline">Propose</NuxtLink> page.
    </p>

    <ul v-else class="space-y-2">
      <li
        v-for="doc in documents"
        :key="doc.id"
        class="rounded border border-neutral-200 dark:border-neutral-800"
      >
        <button
          class="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 text-left"
          @click="expand(doc.id)"
        >
          <span class="rounded px-2 py-0.5 text-xs" :class="sourceClass(doc.source)">
            {{ doc.source }}
          </span>
          <span class="text-sm">{{ doc.title || 'Untitled' }}</span>
          <span class="text-xs text-neutral-500">{{ doc.repository_id }}</span>
          <span class="ml-auto text-xs text-neutral-500">
            {{ doc.observation_count }} observation(s) ·
            {{ clock.dateTime(doc.created_at) }}
          </span>
        </button>

        <div
          v-if="open === doc.id"
          class="border-t border-neutral-200 px-4 py-4 dark:border-neutral-800"
        >
          <p v-if="!loaded[doc.id]" class="text-xs text-neutral-500">Loading…</p>

          <template v-else>
            <p v-if="doc.path" class="mb-3 font-mono text-xs text-neutral-500">
              {{ doc.path }}
            </p>

            <Markdown :source="loaded[doc.id]!.content" />

            <div
              v-if="loaded[doc.id]!.observations.length"
              class="mt-5 border-t border-neutral-200 pt-3 dark:border-neutral-800"
            >
              <h3 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                What came out of it
              </h3>
              <ul class="mt-2 space-y-1 text-sm">
                <li v-for="o in loaded[doc.id]!.observations" :key="o.id">
                  {{ o.title }}
                  <span v-if="o.duplicate_reason" class="text-xs text-amber-700 dark:text-amber-500">
                    — {{ o.duplicate_reason }}
                  </span>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </li>
    </ul>
  </div>
</template>
