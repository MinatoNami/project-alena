<script setup lang="ts">
const { get } = useAlena()
const { data, error } = await useAsyncData('portfolio', () => get<any>('/api/portfolio'))

const sharedDependencies = computed(() =>
  Object.entries(data.value?.shared ?? {})
    .filter(([key]) => key.startsWith('dependency:'))
    .map(([key, users]) => ({ name: key.slice('dependency:'.length), users: users as string[] })),
)
const travelling = computed(() =>
  (data.value?.findings ?? []).filter((f: any) => f.kind === 'travelling-recommendation'),
)
</script>

<template>
  <div>
    <div v-if="error" class="text-sm text-red-700 dark:text-red-400">Cannot reach the API.</div>

    <template v-else-if="data">
      <section v-if="data.divergence?.length" class="mb-8">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Pinned differently across repositories
        </h2>
        <p class="mt-1 text-xs text-neutral-500">
          Nobody decided these; they accumulated. Where two repositories drift furthest apart is where a
          shared fix stops applying cleanly.
        </p>
        <ul class="mt-3 divide-y divide-neutral-200 rounded border border-neutral-200 text-sm dark:divide-neutral-800 dark:border-neutral-800">
          <li v-for="item in data.divergence" :key="item.name" class="px-4 py-2">
            <span class="font-medium">{{ item.name }}</span>
            <span class="ml-2 text-xs text-neutral-500">{{ item.ecosystem }}</span>
            <span class="ml-3 text-xs">
              <span v-for="(spec, repo) in item.specifiers" :key="repo" class="mr-3">
                {{ repo }} <code class="font-mono">{{ spec ?? 'unpinned' }}</code>
              </span>
            </span>
          </li>
        </ul>
      </section>

      <section v-if="travelling.length" class="mb-8">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Work that might travel</h2>
        <p class="mt-1 text-xs text-neutral-500">
          Accepted for one repository, in a technology another one also uses. Nothing is proposed
          automatically — that would let it skip the review every other recommendation goes through.
        </p>
        <ul class="mt-3 space-y-2 text-sm">
          <li v-for="f in travelling" :key="f.title">
            <span class="font-medium">{{ f.title }}</span>
            <span class="ml-2 text-xs text-neutral-500">{{ f.repositories.join(', ') }}</span>
          </li>
        </ul>
      </section>

      <section v-if="sharedDependencies.length">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Shared dependencies</h2>
        <ul class="mt-3 grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
          <li v-for="row in sharedDependencies" :key="row.name" class="flex justify-between gap-4">
            <span>{{ row.name }}</span>
            <span class="text-xs text-neutral-500">{{ row.users.join(', ') }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
