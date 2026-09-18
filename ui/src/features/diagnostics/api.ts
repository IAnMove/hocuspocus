import { BASE } from '../../api/http.ts'
import { parsePack } from './report.ts'
import type { ReportCorrelation, ReportPack } from './types.ts'

async function readPack(response: Response, label: string): Promise<ReportPack> {
  if (!response.ok) {
    throw new Error(`${label} unavailable (${response.status})`)
  }
  return parsePack(await response.json())
}

export async function fetchSnapshot(fetcher: typeof fetch = fetch): Promise<ReportPack> {
  return readPack(await fetcher(`${BASE}/api/v1/diagnostics`), 'diagnostics')
}

export async function fetchReportPack(
  correlation: ReportCorrelation = {},
  fetcher: typeof fetch = fetch,
): Promise<ReportPack> {
  const response = await fetcher(`${BASE}/api/v1/diagnostics/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(correlation),
  })
  return readPack(response, 'diagnostics report')
}
