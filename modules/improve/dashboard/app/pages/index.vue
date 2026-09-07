<script setup lang="ts">
const { get } = useAlena()
const clock = useClock()
clock.load()
const live = ref(true)
const refreshing = ref(false)
const updatedAt = ref<string | null>(null)
const { data, error, refresh, status } = await useAsyncData('status', async () => {
  const result = await get<Status>('/api/status')
  updatedAt.value = new Date().toISOString()
  return result
})
type Activity = { kind: string; at: string; repository_id: string; summary: string; adverse: boolean }
const { data: activity, error: activityError, refresh: refreshActivity } = await useAsyncData('overview-activity', () => get<{ events: Activity[] }>('/api/history?limit=6'))
const stalled = computed(() => data.value?.stages.filter(s => s.stale) ?? [])
const jobIssues = computed(() => data.value?.jobs.filter(j => j.failing || !j.loaded) ?? [])
const attentionCount = computed(() => (data.value?.stranded.length ?? 0) + stalled.value.length + jobIssues.value.length)
const stageNames: Record<string, string> = { unreviewed: 'Review', unscored: 'Score', undecided: 'Decide', unimplemented: 'Implement', unresolved: 'Evaluate' }
const stageLinks: Record<string, string> = { unreviewed: '/research', unscored: '/research', undecided: '/queue', unimplemented: '/queue', unresolved: '/queue' }
async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try { await Promise.all([refresh(), refreshActivity(), refreshNuxtData('overview')]) }
  finally { refreshing.value = false }
}
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { timer = setInterval(() => { if (live.value && !document.hidden) refreshAll() }, 30_000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="overview">
    <div class="page-heading">
      <div><p class="eyebrow">OPERATIONS</p><h1>Overview</h1><p class="muted">Your improvement loop, at a glance.</p></div>
      <div class="refresh-controls">
        <label class="live-control"><input v-model="live" type="checkbox"> Auto-refresh · 30s</label>
        <button class="secondary-button" :disabled="refreshing || status === 'pending'" @click="refreshAll">{{ refreshing ? 'Refreshing…' : '↻ Refresh' }}</button>
        <span class="refresh-time">{{ updatedAt ? `Status updated ${clock.time(updatedAt)}` : 'Waiting for first update' }} {{ updatedAt ? clock.zoneLabel : '' }}</span>
      </div>
    </div>
    <div v-if="error" class="notice danger" role="alert"><strong>Overview unavailable</strong><p>Cannot load current status. Check the dashboard service and try again.</p><button class="text-link" @click="refreshAll">Retry connection →</button></div>
    <template v-else-if="data">
      <div class="health-strip" :class="attentionCount ? 'warning' : ''"><span class="status-dot" /><strong>{{ attentionCount ? 'Attention needed' : 'No pipeline alerts' }}</strong><span>{{ attentionCount ? `${attentionCount} failed reviews, stalled stages or schedule issues to investigate.` : 'No failed reviews, stalled stages or schedule issues reported.' }}</span><a href="#attention" class="text-link">View details ↓</a></div>
      <section class="metric-grid" aria-label="Current workspace metrics">
        <NuxtLink to="/queue" class="metric-card"><span class="metric-label">Awaiting your decision <span>↗</span></span><strong>{{ data.waiting_on_you }}</strong><span class="metric-caption">{{ data.waiting_on_you ? 'Review recommendations to move work forward' : 'No recommendations waiting for approval' }}</span></NuxtLink>
        <a href="#pipeline" class="metric-card"><span class="metric-label">Stalled stages <span>↘</span></span><strong :class="stalled.length ? 'warning-text' : ''">{{ stalled.length }}<small> / {{ data.stages.length }}</small></strong><span class="metric-caption">Work older than its stage threshold</span></a>
        <NuxtLink to="/repositories" class="metric-card"><span class="metric-label">Scan coverage <span>↗</span></span><strong>{{ data.coverage.scanned }}<small> / {{ data.coverage.repositories }}</small></strong><span class="metric-caption">{{ data.coverage.last_scan ? `Latest scan ${clock.dateTime(data.coverage.last_scan)}` : 'No scans recorded yet' }}</span></NuxtLink>
        <NuxtLink to="/research" class="metric-card"><span class="metric-label">Research documents <span>↗</span></span><strong>{{ data.coverage.research_documents }}</strong><span class="metric-caption">Total ingested across repositories</span></NuxtLink>
      </section>
      <div class="overview-columns">
        <section id="pipeline" class="panel">
          <div class="panel-heading"><div><h2>Pipeline workload</h2><p>Current backlog at each hand-off</p></div><span class="pill neutral">CURRENT</span></div>
          <div class="pipeline-stages">
            <NuxtLink v-for="(stage, index) in data.stages" :key="stage.name" :to="stageLinks[stage.name] || '/history'" class="pipeline-stage" :class="{ stalled: stage.stale }">
              <div class="stage-label"><span class="stage-number">0{{ index + 1 }}</span>{{ stageNames[stage.name] || stage.name }}<span aria-hidden="true">→</span></div>
              <strong>{{ stage.count }}</strong><p>{{ stage.label }}</p>
              <span class="stage-age">{{ stage.stale ? 'Stalled · ' : '' }}{{ stage.count && stage.oldest_days !== null ? `Oldest ${stage.oldest_days}d` : stage.count ? 'Age unavailable' : 'Queue clear' }}</span>
            </NuxtLink>
          </div>
          <details class="pipeline-explainer"><summary>How the improvement loop works</summary><PipelineDiagram :stages="data.stages" /></details>
        </section>
        <section class="panel schedule-panel"><div class="panel-heading"><div><h2>Automation</h2><p>Scheduled job status</p></div></div>
          <div v-for="job in data.jobs" :key="job.label" class="schedule-job"><span class="pill" :class="job.running ? 'info' : job.failing ? 'danger' : !job.loaded ? 'warning' : 'neutral'">{{ job.running ? 'Running' : job.failing ? 'Failed' : !job.loaded ? 'Not installed' : 'Loaded' }}</span><h3>{{ job.label === 'local.alena.cycle' ? 'Nightly improvement cycle' : job.label }}</h3><p>{{ job.description }}</p></div>
          <p v-if="!data.jobs.length" class="empty-state">Schedule information is unavailable on this host.</p><a href="#run-controls" class="text-link schedule-link">Open manual controls ↓</a>
        </section>
      </div>
      <section id="attention" class="panel attention-panel"><div class="panel-heading"><div><h2>Needs attention <span class="count-label">{{ attentionCount + (data.waiting_on_you ? 1 : 0) }}</span></h2><p>Issues and decisions with a next step</p></div></div>
        <div v-if="data.waiting_on_you" class="attention-row"><span class="pill info">Decision</span><div><strong>{{ data.waiting_on_you }} recommendations need your review</strong><p>Accept or reject proposals before implementation begins.</p></div><NuxtLink to="/queue" class="text-link">Review decisions →</NuxtLink></div>
        <div v-for="job in jobIssues" :key="job.label" class="attention-row"><span class="pill danger">Schedule</span><div><strong>{{ job.label }}</strong><p>{{ job.description }}. Inspect the scheduler configuration and job logs.</p></div><NuxtLink to="/history" class="text-link">Check activity →</NuxtLink></div>
        <div v-for="stage in stalled" :key="stage.name" class="attention-row"><span class="pill warning">Stalled</span><div><strong>{{ stage.label }}</strong><p>{{ stage.count }} waiting · oldest {{ stage.oldest_days }} days</p><p v-if="stage.examples.length" class="attention-example">{{ stage.examples.join(' · ') }}</p></div><NuxtLink :to="stageLinks[stage.name] || '/history'" class="text-link">Inspect work →</NuxtLink></div>
        <div v-for="(row, index) in data.stranded" :key="`${row.repository_id}-${index}`" class="attention-row"><span class="pill danger">Review failed</span><div><strong>{{ row.title }}</strong><p>{{ row.repository_id }} · Will not retry automatically.</p><details><summary class="text-link">Recovery command</summary><code class="recovery-command">alena-improve review {{ row.repository_id }} --retry-failed</code></details></div><NuxtLink :to="`/repositories/${encodeURIComponent(row.repository_id)}`" class="text-link">Repository →</NuxtLink></div>
        <p v-if="!attentionCount && !data.waiting_on_you" class="empty-state">Nothing waiting for intervention. Review repository signals below for quality concerns.</p>
      </section>
      <RepositoryOverview />
      <section class="panel activity-panel"><div class="panel-heading"><div><h2>Recent activity</h2><p>Latest 6 recorded events · {{ clock.zoneLabel || 'local time' }}</p></div><NuxtLink to="/history" class="text-link">View all activity →</NuxtLink></div>
        <p v-if="activityError" class="empty-state" role="alert">Activity could not be loaded. Use Refresh to try again.</p>
        <template v-else><NuxtLink v-for="(event, index) in activity?.events ?? []" :key="index" :to="`/repositories/${encodeURIComponent(event.repository_id)}`" class="activity-row"><span class="event-marker" :class="{ adverse: event.adverse }"/><div><strong>{{ event.summary }}</strong><p>{{ event.repository_id }} · {{ event.kind }}{{ event.adverse ? ' · Needs review' : '' }}</p></div><time :datetime="event.at">{{ clock.dateTime(event.at) }}</time></NuxtLink><p v-if="!activity?.events.length" class="empty-state">No activity recorded yet. Start a scan using the manual controls below.</p></template>
      </section>
      <section id="run-controls" class="panel manual-panel"><div class="panel-heading"><div><h2>Manual controls</h2><p>Start a cycle or an individual step and follow its output.</p></div></div><div class="panel-body"><RunPanel @finished="refreshAll" /></div></section>
      <p class="overview-footnote">Current pipeline snapshot · Activity is recorded history. Cost, token usage and end-to-end latency are not measured by this dashboard.</p>
    </template>
    <div v-else class="panel empty-state" role="status">Loading workspace status…</div>
  </div>
</template>
