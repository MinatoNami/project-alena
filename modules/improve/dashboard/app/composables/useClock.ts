/**
 * Rendering stored times in the configured zone.
 *
 * Records are stored in UTC; what is shown is the zone the API reports.
 * Served rather than taken from the browser so a page open on a laptop in
 * another country still agrees with the CLI about when something happened.
 */
const zone = ref<string | null>(null)
const zoneLabel = ref<string>('')

export function useClock() {
  const { get } = useAlena()

  async function load() {
    if (zone.value) return
    try {
      const config = await get<{ timezone: string; timezone_label: string }>('/api/config')
      zone.value = config.timezone
      zoneLabel.value = config.timezone_label
    } catch {
      // An unreachable API is reported by the page itself; falling back to
      // the browser's own zone beats rendering nothing.
      zone.value = Intl.DateTimeFormat().resolvedOptions().timeZone
    }
  }

  function format(stamp: string | null | undefined, opts: Intl.DateTimeFormatOptions) {
    if (!stamp) return ''
    const parsed = new Date(stamp)
    if (Number.isNaN(parsed.getTime())) return ''
    return new Intl.DateTimeFormat('en-GB', {
      ...opts,
      timeZone: zone.value ?? undefined,
    }).format(parsed)
  }

  const time = (stamp?: string | null) =>
    format(stamp, { hour: '2-digit', minute: '2-digit', hour12: false })

  const date = (stamp?: string | null) =>
    format(stamp, { year: 'numeric', month: 'short', day: '2-digit' })

  const dateTime = (stamp?: string | null) =>
    format(stamp, {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })

  /** The day a stamp falls on locally, for grouping and for its heading.
   *  Spelled out, because 04/09/2026 is two different days depending on who
   *  is reading it. */
  const dayKey = (stamp?: string | null) =>
    format(stamp, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })

  return { load, zone, zoneLabel, time, date, dateTime, dayKey }
}
