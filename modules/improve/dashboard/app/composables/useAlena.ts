/**
 * The one place that talks to the API.
 *
 * Every state-changing request carries X-Alena-Dashboard. The header's value
 * does not matter; sending a custom header at all forces a CORS preflight,
 * and an origin the API does not allowlist fails that preflight. Without it a
 * page you did not open could POST an approval to your loopback API and the
 * request would arrive.
 */
export function useAlena() {
  const base = useRuntimeConfig().public.apiBase

  async function get<T>(path: string): Promise<T> {
    return await $fetch<T>(`${base}${path}`)
  }

  async function post<T>(path: string, body: unknown): Promise<T> {
    return await $fetch<T>(`${base}${path}`, {
      method: 'POST',
      headers: { 'X-Alena-Dashboard': '1' },
      body,
    })
  }

  return { base, get, post }
}

export type Stage = {
  name: string
  label: string
  count: number
  oldest_days: number | null
  stale: boolean
  examples: string[]
}

export type Status = {
  coverage: {
    repositories: number
    scanned: number
    last_scan: string | null
    last_scan_days: number | null
    research_documents: number
  }
  stages: Stage[]
  jobs: { label: string; loaded: boolean; running: boolean; failing: boolean; description: string }[]
  stranded: { repository_id: string; title: string }[]
  waiting_on_you: number
}

export type Recommendation = {
  id: number
  repository_id: string
  repository_name?: string
  title: string
  status: string
  score: number | null
  confidence: number | null
  estimated_effort: string | null
  reason: string | null
  body: string | null
  breakdown: { priority?: string; dimensions?: Record<string, number> }
}
