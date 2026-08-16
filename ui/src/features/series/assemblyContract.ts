/**
 * Generated from docs/series-lab/series-assembly.openapi.json.
 * Do not edit manually; run scripts/check_series_assembly_contract.py --write.
 */

export type SeriesAssemblyStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface SeriesAssemblyStartRequest {
  workspace?: string | null
}

export interface SeriesAssemblyJobResponse {
  jobId: string
  workspace: string
  seriesId: string
  episodeId: string
  status: SeriesAssemblyStatus
  stage: string
  current: number
  total: number
  message: string
  error?: string | null
  assetId?: string | null
  filename?: string | null
  createdAt?: number | null
  updatedAt?: number | null
  finishedAt?: number | null
}

export type SeriesAssemblyJob = SeriesAssemblyJobResponse
