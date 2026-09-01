import { BASE } from './http'
import type { VideoEditorExportJob } from './video-editor'

export interface MiniMaxImageJob {
  jobId: string
  workspace: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  phase: string
  message: string
  current: number
  total: number
  progress: number
  taskId?: string | null
  rootTaskId?: string | null
  statusCode?: number
  error?: string | null
  result?: { asset: import('../features/comics/types').ComicAsset } | null
}

export async function startComicAnimatic(payload: {
  comic_id: string
  comic_title: string
  width: number
  height: number
  fps: number
  transition: string
  transition_duration: number
  workspace?: string
  panels: Array<{
    source: string
    page_number: number
    panel_number: number
    duration: number
    motion: string
    script: string
  }>
}): Promise<VideoEditorExportJob> {
  const res = await fetch(`${BASE}/api/v1/comics/animatic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not start comic animatic' }))
    throw new Error(error.detail || 'Could not start comic animatic')
  }
  return res.json()
}

// --- Comics ---

export async function saveComicProject(
  project: import('../features/comics/types').ComicProject,
  preview?: string,
  existingName?: string | null,
): Promise<{ name: string; type: 'comic'; url: string; thumbnail_url: string }> {
  const method = existingName ? 'PUT' : 'POST'
  const url = existingName
    ? `${BASE}/api/v1/comics/${encodeURIComponent(existingName)}`
    : `${BASE}/api/v1/comics`
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, preview }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to save comic' }))
    throw new Error(err.detail || 'Failed to save comic')
  }
  return res.json()
}

export async function loadComicProject(name: string): Promise<import('../features/comics/types').ComicProject> {
  const res = await fetch(`${BASE}/api/v1/comics/${encodeURIComponent(name)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load comic' }))
    throw new Error(err.detail || 'Failed to load comic')
  }
  const data = await res.json()
  return data.project
}

export interface ComicHistoryEntry {
  id: string
  comicId: string
  title: string
  createdAt: string
  reason: string
  persistedName: string | null
  pageCount: number
  assetCount: number
}

export async function createComicHistory(
  project: import('../features/comics/types').ComicProject,
  reason = 'Automatic checkpoint',
  persistedName?: string | null,
): Promise<ComicHistoryEntry> {
  const res = await fetch(`${BASE}/api/v1/comics/history`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, reason, persisted_name: persistedName || null }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to back up comic' }))
    throw new Error(err.detail || 'Failed to back up comic')
  }
  return res.json()
}

export async function listComicHistory(comicId?: string): Promise<ComicHistoryEntry[]> {
  const query = comicId ? `?comic_id=${encodeURIComponent(comicId)}` : ''
  const res = await fetch(`${BASE}/api/v1/comics/history${query}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load comic history' }))
    throw new Error(err.detail || 'Failed to load comic history')
  }
  const data = await res.json()
  return data.history || []
}

export async function loadComicHistory(id: string): Promise<{
  project: import('../features/comics/types').ComicProject
  entry: ComicHistoryEntry
}> {
  const res = await fetch(`${BASE}/api/v1/comics/history/${encodeURIComponent(id)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to restore comic backup' }))
    throw new Error(err.detail || 'Failed to restore comic backup')
  }
  return res.json()
}

export async function generateComicWithMiniMax(params: {
  prompt: string
  aspect_ratio: string
  subject_reference?: string
}): Promise<{ asset: import('../features/comics/types').ComicAsset }> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax generation failed' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax generation failed'}`)
  }
  return res.json()
}

export async function startMiniMaxImageJob(params: {
  prompt: string
  aspect_ratio: string
  subject_reference?: string
  workspace: string
}): Promise<MiniMaxImageJob> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax generation failed' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax generation failed'}`)
  }
  return res.json()
}

export async function fetchMiniMaxImageJob(jobId: string): Promise<MiniMaxImageJob> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax/jobs/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax image job not found' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax image job not found'}`)
  }
  return res.json()
}

export type ComicPlanProgress = {
  jobId?: string
  taskId?: string | null
  rootTaskId?: string | null
  status: 'queued' | 'loading_llm' | 'planning' | 'planning_bible' | 'planning_page' | 'completed' | 'failed'
  message: string
  provider?: string
  model?: string
  createdAt?: number
  current?: number
  total?: number
  stage?: 'bible' | 'page'
  page?: number
}

export async function planComic(
  params: import('../features/comics/types').ComicDirectorRequest & { workspace?: string },
  onProgress?: (progress: ComicPlanProgress) => void,
  signal?: AbortSignal,
): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  const start = await fetch(`${BASE}/api/v1/director/comic/plan/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,
  })
  if (!start.ok) {
    const err = await start.json().catch(() => ({ detail: 'Comic planning failed to start' }))
    throw new Error(err.detail || 'Comic planning failed')
  }
  const accepted = await start.json() as ComicPlanProgress & { jobId: string }
  try {
    window.localStorage.setItem('maestro-last-comic-plan-job', accepted.jobId)
  } catch {
    // Recovery still works by manually entering the job ID.
  }
  onProgress?.(accepted)
  for (;;) {
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        window.clearTimeout(timer)
        reject(new DOMException('Comic planning cancelled', 'AbortError'))
      }
      const timer = window.setTimeout(() => {
        signal?.removeEventListener('abort', onAbort)
        resolve()
      }, 1000)
      signal?.addEventListener('abort', onAbort, { once: true })
    })
    const response = await fetch(
      `${BASE}/api/v1/director/comic/plan/status/${encodeURIComponent(accepted.jobId)}`,
      { signal },
    )
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Could not read comic planning status' }))
      throw new Error(err.detail || 'Could not read comic planning status')
    }
    const status = await response.json() as ComicPlanProgress & {
      error?: string
      result?: { plan: import('../features/comics/types').ComicPlan }
    }
    onProgress?.(status)
    if (status.status === 'failed') throw new Error(status.error || status.message)
    if (status.status === 'completed') {
      if (!status.result?.plan) throw new Error('Comic Director completed without a plan')
      try {
        window.localStorage.setItem('maestro-last-comic-plan-result', JSON.stringify({
          jobId: accepted.jobId,
          plan: status.result.plan,
        }))
      } catch {
        // The server job remains recoverable while Maestro is running.
      }
      return status.result
    }
  }
}

export async function fetchComicPlanJob(jobId: string): Promise<{
  jobId: string
  status: ComicPlanProgress['status']
  message: string
  error?: string
  request?: import('../features/comics/types').ComicDirectorRequest
  result?: { plan: import('../features/comics/types').ComicPlan }
}> {
  const response = await fetch(
    `${BASE}/api/v1/director/comic/plan/status/${encodeURIComponent(jobId)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic planning job not found' }))
    throw new Error(error.detail || 'Comic planning job not found')
  }
  return response.json()
}

export async function resumeComicPlanJob(jobId: string): Promise<{
  jobId: string
  status: ComicPlanProgress['status']
  message: string
}> {
  const response = await fetch(
    `${BASE}/api/v1/director/comic/plan/resume/${encodeURIComponent(jobId)}`,
    { method: 'POST' },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not resume comic planning' }))
    throw new Error(error.detail || 'Could not resume comic planning')
  }
  return response.json()
}

export async function waitForComicPlanJob(
  jobId: string,
  onProgress?: (progress: ComicPlanProgress) => void,
): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  for (;;) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    const job = await fetchComicPlanJob(jobId)
    onProgress?.(job)
    if (job.status === 'failed') throw new Error(job.error || job.message)
    if (job.status === 'completed') {
      if (!job.result?.plan) throw new Error('Comic Director completed without a plan')
      try {
        window.localStorage.setItem('maestro-last-comic-plan-result', JSON.stringify({
          jobId,
          plan: job.result.plan,
        }))
      } catch {
        // The durable server checkpoint remains available.
      }
      return job.result
    }
  }
}

export async function fetchLatestCompletedComicPlan(): Promise<{
  jobId: string
  request?: import('../features/comics/types').ComicDirectorRequest
  result: { plan: import('../features/comics/types').ComicPlan }
  finishedAt?: number
}> {
  const response = await fetch(`${BASE}/api/v1/director/comic/plan/recent/completed`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'No completed comic plan is available' }))
    throw new Error(error.detail || 'No completed comic plan is available')
  }
  return response.json()
}

export async function rewriteComicTextPage(params: {
  plan: import('../features/comics/types').ComicPlan
  pageIndex: number
  mode: 'rewrite' | 'translate'
  instruction?: string
  targetLanguage?: string
  dialogueDensity: import('../features/comics/types').ComicDirectorRequest['dialogueDensity']
  glossary?: import('../features/comics/types').ComicGlossaryEntry[]
  writingProvider?: import('../features/comics/types').ComicDirectorRequest['writingProvider']
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ page: import('../features/comics/types').ComicPlanPage }> {
  const response = await fetch(`${BASE}/api/v1/director/comic/text/page`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic text operation failed' }))
    throw new Error(error.detail || 'Comic text operation failed')
  }
  return response.json()
}

export async function reviseComicStory(params: {
  plan: import('../features/comics/types').ComicPlan
  instruction?: string
  dialogueDensity: import('../features/comics/types').ComicDirectorRequest['dialogueDensity']
  productionMode?: import('../features/comics/types').ComicDirectorRequest['productionMode']
  writingProvider?: import('../features/comics/types').ComicDirectorRequest['writingProvider']
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  const response = await fetch(`${BASE}/api/v1/director/comic/story/revise`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic story revision failed' }))
    throw new Error(error.detail || 'Comic story revision failed')
  }
  return response.json()
}
