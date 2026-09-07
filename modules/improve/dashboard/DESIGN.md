# Dashboard design rationale

## Existing implementation

The dashboard is a Nuxt SPA backed by the existing FastAPI adapter. Its useful operational signals were arranged as a long status report: coverage text, pipeline rows, a wide repository table, schedule descriptions, failed reviews, manual controls, and finally pending decisions. The status request refreshed every 30 seconds, but repository signals did not. Repository fetch failures appeared as an empty table. The navigation could overflow on a phone.

## Research and application

Sources reviewed on 7 September 2026:

- [Grafana dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/): start with an operational question, progress from overview to details, keep visualizations focused, use consistent status colors, and provide drill-down links. Applied through snapshot cards, ordered pipeline stages, restrained amber/red exception states, and links into existing detail pages.
- [Datadog dashboard planning](https://docs.datadoghq.com/getting_started/dashboards/): prioritize the information teams frequently need and make the dashboard support investigation. Applied through a prominent attention section, recovery guidance, recent activity, and manual controls.
- [Langfuse metrics](https://langfuse.com/docs/metrics/overview): use measured signals and relevant dimensions to investigate quality and operation. Applied through searchable repositories, a needs-attention filter, quality signals, and explicit measurement limitations.

This is a repository improvement workflow, so its useful signals are outstanding decisions, stalled hand-offs, failed reviews, scan coverage, and scheduler state. Generic infrastructure graphs would not answer those questions.

## Behavior

- Shared sidebar separates monitoring from work management; mobile navigation scrolls within its own region.
- Overview cards link to the relevant work. Pipeline values are current backlog, not throughput or historical trends.
- Attention counts are failed review records + stalled stages + failing/uninstalled jobs. Pending decisions are one additional grouped row, with their actual recommendation count stated inside it. Counts are not unique incidents.
- Repository rows sort by quality issue count, then pending decisions, then name. Search and attention filters apply only to that table, with explicit empty and failure states.
- Refresh reloads status, repository overview, and recent activity together. Auto-refresh can be paused and skips hidden tabs; leaving the page clears its interval. The timestamp explicitly refers to the status response.
- Scheduler states retain the backend distinction between running, failing, loaded, and not installed. Loaded alone does not imply a successful previous run. Missing scheduler information is shown as unavailable.
- Recent activity is the six latest recorded events, not an arbitrary time-window aggregate.
- Existing approval and implementation gates are preserved. No jobs are started by opening or refreshing the overview.
- Run controls disable immediately during submission, resume polling an existing run on mount, show connection failures, and stop polling on unmount.
- Light and dark palettes follow system preference. Status text accompanies color; controls have focus indicators and accessible labels.

## Measurement boundaries

The existing API does not expose historical workload snapshots, end-to-end latency, token use, or cost series. These are not fabricated or estimated. Scan coverage means a repository has ever been scanned; it does not imply that every scan is fresh. The last scan timestamp describes the latest scan, not the oldest repository scan. Repository quality issues remain separate from pipeline alerts.

## Verification

Production static generation; existing web API, run, status, and history tests; browser checks using isolated API fixtures for desktop, mobile, dark mode, repository search and attention filtering, refresh, empty data, partial API failure, and status failure/recovery. Fixture tests do not invoke real agent jobs or change recommendations.
