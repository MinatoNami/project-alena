<script setup lang="ts">
// The same pass the nightly job runs, drawn once, with the counts from the
// rows above it sitting in the gaps where work actually waits.
//
// Inline SVG rather than a diagramming library: this is one fixed diagram, and
// a dependency that renders it would be downloaded on every page load to draw
// something that never changes shape. Colour comes from Tailwind classes so it
// follows the theme; geometry is attributes, because utility classes for
// font-size do not reliably reach SVG text.

type Stage = { name: string; label: string; count: number; stale: boolean }

const props = defineProps<{ stages?: Stage[] }>()

const STEPS = [
  { key: 'scan', label: 'scan', note: 'git, deps, TODOs' },
  { key: 'ingest', label: 'ingest', note: 'research dropped' },
  { key: 'review', label: 'review', note: 'Codex, per observation' },
  { key: 'score', label: 'score', note: 'dedup and rank' },
  { key: 'decide', label: 'you decide', note: 'the gate' },
  { key: 'implement', label: 'implement', note: 'on a branch' },
  { key: 'outcome', label: 'outcome', note: 'worked or did not' },
]

// Which waiting count belongs in the gap *before* each step. `unreviewed`
// waits to be reviewed, `undecided` waits for the gate, and so on.
const WAITING: Record<string, string> = {
  review: 'unreviewed',
  score: 'unscored',
  decide: 'undecided',
  implement: 'unimplemented',
  outcome: 'unresolved',
}

const BOX_W = 132
const PITCH = 172
const BOX_Y = 46
const BOX_H = 46

const byName = computed(() => {
  const map: Record<string, Stage> = {}
  for (const stage of props.stages ?? []) map[stage.name] = stage
  return map
})

const nodes = computed(() =>
  STEPS.map((step, i) => {
    const stage = byName.value[WAITING[step.key] ?? '']
    return {
      ...step,
      x: 10 + i * PITCH,
      // The gap to this node's left, where anything waiting for it sits.
      gapX: 10 + i * PITCH - (PITCH - BOX_W) / 2,
      waiting: stage ?? null,
    }
  }),
)

const width = 10 + STEPS.length * PITCH - (PITCH - BOX_W) + 10
</script>

<template>
  <div class="overflow-x-auto">
    <svg
      :viewBox="`0 0 ${width} 132`"
      :width="width"
      role="img"
      aria-label="The nightly pass: scan, ingest, review, score, then your decision, then the action agent."
      class="max-w-none"
    >
      <defs>
        <marker
          id="pipeline-arrow"
          viewBox="0 0 8 8"
          refX="7"
          refY="4"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M0,0 L8,4 L0,8 z" class="fill-neutral-400 dark:fill-neutral-600" />
        </marker>
      </defs>

      <!-- What runs unattended, and what does not. The bracket is the whole
           point of the drawing: everything under it happens overnight. -->
      <path
        :d="`M10,26 L10,18 L${10 + 4 * PITCH - (PITCH - BOX_W)},18 L${10 + 4 * PITCH - (PITCH - BOX_W)},26`"
        fill="none"
        stroke-dasharray="3 3"
        class="stroke-neutral-300 dark:stroke-neutral-700"
      />
      <text
        :x="(10 + (10 + 4 * PITCH - (PITCH - BOX_W))) / 2"
        y="13"
        text-anchor="middle"
        font-size="10"
        class="fill-neutral-500"
      >
        nightly 02:00, automatic — nothing here touches a repository
      </text>

      <g v-for="(node, i) in nodes" :key="node.key">
        <!-- the arrow into this node, and whatever is waiting in it -->
        <template v-if="i > 0">
          <line
            :x1="node.x - (PITCH - BOX_W) + 4"
            :y1="BOX_Y + BOX_H / 2"
            :x2="node.x - 6"
            :y2="BOX_Y + BOX_H / 2"
            class="stroke-neutral-400 dark:stroke-neutral-600"
            marker-end="url(#pipeline-arrow)"
          />
          <text
            v-if="node.waiting"
            :x="node.gapX"
            :y="BOX_Y - 6"
            text-anchor="middle"
            font-size="10"
            :class="
              node.waiting.stale
                ? 'fill-amber-600 dark:fill-amber-500'
                : node.waiting.count
                  ? 'fill-neutral-600 dark:fill-neutral-400'
                  : 'fill-neutral-400 dark:fill-neutral-600'
            "
          >
            {{ node.waiting.count || 'none' }}
          </text>
        </template>

        <rect
          :x="node.x"
          :y="BOX_Y"
          :width="BOX_W"
          :height="BOX_H"
          rx="4"
          class="fill-transparent"
          :stroke-width="node.key === 'decide' ? 2 : 1"
          :class="
            node.key === 'decide'
              ? 'stroke-amber-600 dark:stroke-amber-500'
              : 'stroke-neutral-300 dark:stroke-neutral-700'
          "
        />
        <text
          :x="node.x + BOX_W / 2"
          :y="BOX_Y + 20"
          text-anchor="middle"
          font-size="12"
          :class="
            node.key === 'decide'
              ? 'fill-amber-700 dark:fill-amber-500'
              : 'fill-neutral-800 dark:fill-neutral-200'
          "
        >
          {{ node.label }}
        </text>
        <text
          :x="node.x + BOX_W / 2"
          :y="BOX_Y + 35"
          text-anchor="middle"
          font-size="10"
          class="fill-neutral-500"
        >
          {{ node.note }}
        </text>
      </g>

      <text x="10" y="126" font-size="10" class="fill-neutral-500">
        Counts are what is waiting at each hand-off. The action agent runs only on an accepted
        recommendation, on a branch, and never pushes.
      </text>
    </svg>
  </div>
</template>
