<script setup lang="ts">
const links = [
  { to: '/', label: 'Status' },
  { to: '/queue', label: 'Queue' },
  { to: '/propose', label: 'Propose' },
  { to: '/repositories', label: 'Repositories' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/tools', label: 'Tools' },
]
</script>

<template>
  <div class="min-h-screen bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
    <header class="border-b border-neutral-200 dark:border-neutral-800">
      <div class="mx-auto flex max-w-5xl flex-wrap items-baseline gap-x-6 gap-y-2 px-6 py-4">
        <NuxtLink to="/" class="text-sm font-semibold tracking-tight">ALENA</NuxtLink>
        <nav class="flex gap-4 text-sm">
          <NuxtLink
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
            active-class="text-neutral-900 font-medium dark:text-neutral-100"
          >{{ link.label }}</NuxtLink>
        </nav>
      </div>
    </header>
    <main class="mx-auto max-w-5xl px-6 py-8">
      <NuxtPage />
    </main>
  </div>
</template>
