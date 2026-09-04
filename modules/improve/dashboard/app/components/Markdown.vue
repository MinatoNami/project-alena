<script setup lang="ts">
/**
 * Research rendered as markdown, without rendering it as HTML.
 *
 * Research text is written by an external agent reading the public internet.
 * Handing it to a markdown library that emits HTML would put attacker-authored
 * markup into the dashboard, so this parses into blocks and renders every
 * piece of text through Vue's interpolation, which escapes it.
 *
 * Links are the one thing that becomes an element, and only when the URL is
 * http or https -- so a `javascript:` href in a research document renders as
 * the text it is.
 */
const props = defineProps<{ source: string }>()

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'item'; text: string }
  | { type: 'code'; text: string }

const blocks = computed<Block[]>(() => {
  const out: Block[] = []
  const lines = (props.source ?? '').split('\n')
  let paragraph: string[] = []
  let code: string[] | null = null

  const flush = () => {
    if (paragraph.length) {
      out.push({ type: 'paragraph', text: paragraph.join(' ').trim() })
      paragraph = []
    }
  }

  for (const line of lines) {
    if (line.trimStart().startsWith('```')) {
      if (code) {
        out.push({ type: 'code', text: code.join('\n') })
        code = null
      } else {
        flush()
        code = []
      }
      continue
    }
    if (code) { code.push(line); continue }

    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      flush()
      out.push({ type: 'heading', level: heading[1]!.length, text: heading[2]!.trim() })
      continue
    }
    const item = line.match(/^\s*[-*]\s+(.*)$/)
    if (item) {
      flush()
      out.push({ type: 'item', text: item[1]!.trim() })
      continue
    }
    if (!line.trim()) { flush(); continue }
    paragraph.push(line.trim())
  }
  flush()
  if (code) out.push({ type: 'code', text: code.join('\n') })
  return out
})

/** Split text into plain runs and safe links, both rendered as text. */
function parts(text: string) {
  const out: { text: string; href?: string }[] = []
  const pattern = /https?:\/\/[^\s<>"')\]]+/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0
    if (at > last) out.push({ text: text.slice(last, at) })
    out.push({ text: match[0], href: match[0] })
    last = at + match[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

/** Emphasis markers, stripped rather than turned into elements. */
const plain = (text: string) =>
  text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/(^|\s)_(.+?)_(?=\s|$|[.,])/g, '$1$2')
</script>

<template>
  <div class="space-y-3 text-sm leading-relaxed">
    <template v-for="(block, index) in blocks" :key="index">
      <p
        v-if="block.type === 'heading'"
        class="font-semibold"
        :class="block.level <= 2 ? 'text-base' : 'text-sm'"
      >{{ plain(block.text) }}</p>

      <pre
        v-else-if="block.type === 'code'"
        class="overflow-x-auto rounded bg-neutral-100 p-3 font-mono text-xs dark:bg-neutral-900"
      >{{ block.text }}</pre>

      <p v-else :class="block.type === 'item' ? 'pl-4 -indent-3' : ''">
        <span v-if="block.type === 'item'">— </span>
        <template v-for="(part, i) in parts(plain(block.text))" :key="i">
          <a
            v-if="part.href"
            :href="part.href"
            target="_blank"
            rel="noopener noreferrer nofollow"
            class="underline decoration-dotted"
          >{{ part.text }}</a>
          <template v-else>{{ part.text }}</template>
        </template>
      </p>
    </template>
  </div>
</template>
