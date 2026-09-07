<script setup lang="ts">
const route = useRoute()
const links = [
  { to: '/', label: 'Overview', icon: '◫', group: 'Monitor' },
  { to: '/history', label: 'Activity', icon: '◷', group: 'Monitor' },
  { to: '/tools', label: 'Tool health', icon: '⌁', group: 'Monitor' },
  { to: '/queue', label: 'Decisions', icon: '☷', group: 'Workspace' },
  { to: '/repositories', label: 'Repositories', icon: '▱', group: 'Workspace' },
  { to: '/research', label: 'Research', icon: '▤', group: 'Workspace' },
  { to: '/portfolio', label: 'Portfolio', icon: '⊞', group: 'Workspace' },
  { to: '/propose', label: 'Propose an idea', icon: '+', group: 'Workspace' },
]
const title = computed(() => links.find(l => l.to === route.path)?.label ?? 'Repository details')
</script>

<template>
  <div class="app-shell">
    <a href="#main-content" class="skip-link">Skip to content</a>
    <aside class="sidebar">
      <NuxtLink to="/" class="brand"><span class="brand-mark">a</span><span>alena<span class="brand-sub">IMPROVEMENT WORKSPACE</span></span></NuxtLink>
      <nav aria-label="Main navigation">
        <div v-for="group in ['Monitor', 'Workspace']" :key="group" class="nav-group">
          <p class="eyebrow">{{ group }}</p>
          <NuxtLink v-for="link in links.filter(l => l.group === group)" :key="link.to" :to="link.to" class="nav-link" :class="{ selected: link.to === '/' ? route.path === '/' : route.path.startsWith(link.to) }">
            <span aria-hidden="true" class="nav-icon">{{ link.icon }}</span>{{ link.label }}
          </NuxtLink>
        </div>
      </nav>
      <div class="sidebar-footer"><span class="local-dot" /> Local workspace<p>Observe. Review. Improve.</p></div>
    </aside>
    <div class="workspace">
      <header class="workspace-header"><span>Workspace <span class="breadcrumb-divider">/</span> <strong>{{ title }}</strong></span><span class="environment">LOCAL</span></header>
      <main id="main-content" class="workspace-main">
        <div v-if="route.path !== '/'" class="page-heading"><div><p class="eyebrow">ALENA WORKSPACE</p><h1>{{ title }}</h1></div></div>
        <NuxtPage />
      </main>
    </div>
  </div>
</template>
