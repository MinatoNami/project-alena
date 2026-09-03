<script setup lang="ts">
const route = useRoute()
const { get } = useAlena()
const id = route.params.id as string
const { data: profile, error } = await useAsyncData(`repo-${id}`, () => get<any>(`/api/repositories/${id}`))
const { data: recommendations } = await useAsyncData(`recs-${id}`, () =>
  get<Recommendation[]>(`/api/repositories/${id}/recommendations`),
)
</script>

<template>
  <div>
    <div v-if="error" class="rounded border border-neutral-300 p-4 text-sm dark:border-neutral-700">
      Not scanned yet. <span class="font-mono text-xs">alena-improve scan {{ id }}</span>
    </div>

    <template v-else-if="profile">
      <h1 class="text-lg font-medium">{{ profile.name }}</h1>
      <p class="mt-1 text-xs text-neutral-500">
        {{ profile.branch }} @ {{ (profile.head_sha || '').slice(0, 8) }} ·
        {{ profile.file_count }} files · {{ profile.dependencies?.length ?? 0 }} dependencies ·
        {{ profile.todos?.length ?? 0 }} TODOs
      </p>

      <section v-if="profile.summary" class="mt-6">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Summary</h2>
        <p class="mt-2 text-sm leading-relaxed text-neutral-700 dark:text-neutral-300">{{ profile.summary }}</p>
      </section>

      <section v-if="Object.keys(profile.languages || {}).length" class="mt-6">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Languages</h2>
        <p class="mt-2 text-sm">
          <span v-for="(count, name) in profile.languages" :key="name" class="mr-4">
            {{ name }} <span class="text-neutral-500">{{ count }}</span>
          </span>
        </p>
      </section>

      <section v-if="recommendations?.length" class="mt-6">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Recommendations</h2>
        <ul class="mt-2 space-y-1 text-sm">
          <li v-for="row in recommendations" :key="row.id" class="flex gap-3">
            <span class="w-24 shrink-0 text-xs text-neutral-500">{{ row.status }}</span>
            <span>{{ row.title }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
