<script setup lang="ts">
const { get, post } = useAlena()
const { data: repositories } = await useAsyncData('repos-for-propose', () =>
  get<{ id: string; name: string }[]>('/api/repositories'),
)

const repository = ref('')
const title = ref('')
const body = ref('')
const evidence = ref('')
const busy = ref(false)
const result = ref<{ duplicate: boolean; message: string; observation_id: number } | null>(null)
const failure = ref<string | null>(null)

watchEffect(() => {
  if (!repository.value && repositories.value?.length) repository.value = repositories.value[0]!.id
})

async function submit() {
  busy.value = true
  failure.value = null
  result.value = null
  try {
    result.value = await post('/api/observations', {
      repository_id: repository.value,
      title: title.value,
      body: body.value,
      evidence: evidence.value || undefined,
    })
    if (!result.value?.duplicate) {
      title.value = ''
      body.value = ''
      evidence.value = ''
    }
  } catch (e: any) {
    failure.value = e?.data?.detail ?? e?.message ?? 'Could not record it.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl">
    <h1 class="text-base font-medium">Propose something</h1>
    <p class="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
      An idea of your own, entering the pipeline where research does. It is de-duplicated, put to the
      engineering reviewer, scored and brought back to you for a decision — the same path, so the
      review scrutinises your ideas as well as the ones nobody is attached to.
    </p>

    <div class="mt-6 space-y-4">
      <div>
        <label class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Repository</label>
        <select
          v-model="repository"
          class="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        >
          <option v-for="repo in repositories" :key="repo.id" :value="repo.id">{{ repo.name }}</option>
        </select>
      </div>

      <div>
        <label class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Title</label>
        <input
          v-model="title"
          class="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          placeholder="Cache rendered page thumbnails on disk"
        >
      </div>

      <div>
        <label class="text-xs font-semibold uppercase tracking-wide text-neutral-500">What and why</label>
        <textarea
          v-model="body"
          rows="6"
          class="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          placeholder="The reader regenerates cover mosaics on every load…"
        />
      </div>

      <div>
        <label class="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Evidence (optional)
        </label>
        <input
          v-model="evidence"
          class="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          placeholder="https://…"
        >
        <p class="mt-1 text-xs text-neutral-500">
          Counted when scoring. An uncited proposal is not refused, it just scores lower on evidence.
        </p>
      </div>

      <button
        class="rounded bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-40 dark:bg-neutral-100 dark:text-neutral-900"
        :disabled="!title.trim() || busy"
        @click="submit"
      >{{ busy ? 'Recording…' : 'Propose' }}</button>
    </div>

    <p
      v-if="failure"
      class="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950"
    >{{ failure }}</p>

    <div
      v-if="result"
      class="mt-4 rounded border p-3 text-sm"
      :class="result.duplicate
        ? 'border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950'
        : 'border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950'"
    >
      <p>{{ result.message }}</p>
      <p v-if="!result.duplicate" class="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
        Run <span class="font-medium">Review new observations</span> from the status page to have it
        assessed.
      </p>
    </div>
  </div>
</template>
