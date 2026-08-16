/**
 * Generated from docs/series-lab/series-assembly.openapi.json.
 * Do not edit manually; run scripts/check_series_assembly_contract.py --write.
 */

export type SeriesAssemblyStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface SeriesAssemblyStartRequest {
  workspace?: string | null
}

export interface SeriesAssemblyActionRequest {
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

export interface SeriesAssemblyRecoveryResponse {
  jobs: SeriesAssemblyJobResponse[]
}

export interface SeriesAssemblyDiscardResponse {
  discarded: boolean
  jobId: string
  outputsPreserved: boolean
}

export type SeriesAssemblyJob = SeriesAssemblyJobResponse
