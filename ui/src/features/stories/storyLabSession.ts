import { useEffect, useRef, useState } from 'react'
import type { StoryGenerationScope } from './types'

export type StoryLabPendingDraft = {
  scope: StoryGenerationScope
  result: Record<string, unknown>
  selected: string[]
  replaceCollections: boolean
  generateImagesAfterApply: boolean
}

export type StoryLabSessionRecord = {
  jobId?: string
  scope?: StoryGenerationScope
  result?: Record<string, unknown>
  generateImagesAfterApply?: boolean
}

export type StoryLabSessionStatus = {
  status: string
  result?: { result?: Record<string, unknown> } | null
}

export const storyJobKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-job:${workspace}:${projectId}`
export const storyResultKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-result:${workspace}:${projectId}`

export function draftPaths(result: Record<string, unknown>): string[] {
  const paths: string[] = []
  if (result.overview && typeof result.overview === 'object') {
    Object.entries(result.overview as Record<string, unknown>).forEach(([key, value]) => {
      if (key === 'creativeBrief' && value && typeof value === 'object') {
        Object.keys(value).forEach(field => paths.push(`overview.creativeBrief.${field}`))
      } else {
        paths.push(`overview.${key}`)
      }
    })
  }
  if (result.world && typeof result.world === 'object') {
    Object.keys(result.world).forEach(key => paths.push(`world.${key}`))
  }
  if (Array.isArray(result.characters)) {
    result.characters.forEach((item, index) => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>
        const id = String(record.id || index)
        Object.keys(record)
          .filter(key => !['id', 'referenceAssetIds', 'primaryReferenceAssetId', 'approval'].includes(key))
          .forEach(key => paths.push(`characters.${id}.${key}`))
      }
    })
  }
  if (Array.isArray(result.relationships)) {
    result.relationships.forEach((item, index) => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>
        const id = String(record.id || index)
        Object.keys(record).filter(key => key !== 'id')
          .forEach(key => paths.push(`relationships.${id}.${key}`))
      }
    })
  }
  const structure = Array.isArray(result.structure) ? result.structure
    : Array.isArray(result.beats) ? result.beats : []
  structure.forEach((item, index) => {
    if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      const id = String(record.id || index)
      Object.keys(record).filter(key => key !== 'id')
        .forEach(key => paths.push(`structure.${id}.${key}`))
    }
  })
  const music = result.music && typeof result.music === 'object'
    ? result.music as Record<string, unknown> : null
  if (music && Array.isArray(music.cues)) {
    music.cues.forEach((item, index) => {
      if (!item || typeof item !== 'object') return
      const record = item as Record<string, unknown>
      paths.push(`music.${String(record.id || index)}`)
    })
  }
  return paths
}

export function readStoryLabJobId(workspace: string, projectId: string): string {
  return window.localStorage.getItem(storyJobKey(workspace, projectId)) || ''
}

export function readStoryLabSessionRecord(
  workspace: string,
  projectId: string,
): StoryLabSessionRecord | null {
  try {
    const saved = JSON.parse(window.localStorage.getItem(storyResultKey(workspace, projectId)) || 'null')
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return null
    return saved as StoryLabSessionRecord
  } catch {
    return null
  }
}

export function pendingDraftFromRecord(
  record: StoryLabSessionRecord | null,
): StoryLabPendingDraft | null {
  if (!record?.result || typeof record.result !== 'object' || Array.isArray(record.result)) return null
  return {
    scope: record.scope || 'all',
    result: record.result,
    selected: draftPaths(record.result),
    replaceCollections: true,
    generateImagesAfterApply: record.generateImagesAfterApply === true,
  }
}

export function persistStoryLabJob(workspace: string, projectId: string, jobId: string): void {
  window.localStorage.setItem(storyJobKey(workspace, projectId), jobId)
}

export function persistStoryLabSessionRecord(
  workspace: string,
  projectId: string,
  record: StoryLabSessionRecord,
): void {
  window.localStorage.setItem(storyResultKey(workspace, projectId), JSON.stringify(record))
}

export function clearStoryLabSession(workspace: string, projectId: string): void {
  window.localStorage.removeItem(storyResultKey(workspace, projectId))
  window.localStorage.removeItem(storyJobKey(workspace, projectId))
}

export function applyRecoveredStoryLabStatus(options: {
  disposed: boolean
  workspace: string
  projectId: string
  jobId: string
  savedScope: StoryGenerationScope
  generateImagesAfterApply: boolean
  status: StoryLabSessionStatus
}): StoryLabPendingDraft | null {
  const result = options.status.status === 'completed' ? options.status.result?.result : null
  if (options.disposed || !result) return null
  persistStoryLabSessionRecord(options.workspace, options.projectId, {
    jobId: options.jobId,
    scope: options.savedScope,
    result,
    generateImagesAfterApply: options.generateImagesAfterApply,
  })
  return pendingDraftFromRecord({
    jobId: options.jobId,
    scope: options.savedScope,
    result,
    generateImagesAfterApply: options.generateImagesAfterApply,
  })
}

export type UseStoryLabSessionOptions = {
  workspace: string
  projectId: string
  revision?: number
  loadWorkspace: (workspace: string) => void | Promise<void>
  getStoryGenerationStatus: (jobId: string) => Promise<StoryLabSessionStatus>
  onRecoveredServerResult?: () => void
}

export function useStoryLabSession({
  workspace,
  projectId,
  revision = 0,
  loadWorkspace,
  getStoryGenerationStatus,
  onRecoveredServerResult,
}: UseStoryLabSessionOptions) {
  const sessionOwner = `${workspace}:${projectId}:${revision}`
  const [ownedSession, setOwnedSession] = useState(sessionOwner)
  const [recoveryJobId, setRecoveryJobId] = useState(() => readStoryLabJobId(workspace, projectId))
  const [pendingDraft, setPendingDraft] = useState<StoryLabPendingDraft | null>(() => (
    pendingDraftFromRecord(readStoryLabSessionRecord(workspace, projectId))
  ))
  if (ownedSession !== sessionOwner) {
    setOwnedSession(sessionOwner)
    setRecoveryJobId(readStoryLabJobId(workspace, projectId))
    setPendingDraft(pendingDraftFromRecord(readStoryLabSessionRecord(workspace, projectId)))
  }
  const generationAbortRef = useRef<AbortController | null>(null)
  const getStatusRef = useRef(getStoryGenerationStatus)
  const onRecoveredRef = useRef(onRecoveredServerResult)

  useEffect(() => {
    getStatusRef.current = getStoryGenerationStatus
    onRecoveredRef.current = onRecoveredServerResult
  })

  useEffect(() => {
    void loadWorkspace(workspace)
  }, [workspace, loadWorkspace])

  useEffect(() => {
    const savedJobId = readStoryLabJobId(workspace, projectId)
    const saved = readStoryLabSessionRecord(workspace, projectId)
    const draft = pendingDraftFromRecord(saved)
    let disposed = false
    if (savedJobId && !draft) {
      void getStatusRef.current(savedJobId).then(status => {
        const recovered = applyRecoveredStoryLabStatus({
          disposed,
          workspace,
          projectId,
          jobId: savedJobId,
          savedScope: saved?.scope || 'all',
          generateImagesAfterApply: saved?.generateImagesAfterApply === true,
          status,
        })
        if (!recovered) return
        setPendingDraft(recovered)
        onRecoveredRef.current?.()
      }).catch(() => {
        // The visible Resume control remains available for failed, cancelled,
        // temporarily unreachable, or still-running checkpoints.
      })
    }
    return () => { disposed = true }
  }, [workspace, projectId, revision])

  useEffect(() => () => {
    generationAbortRef.current?.abort()
  }, [])

  return {
    recoveryJobId,
    setRecoveryJobId,
    pendingDraft,
    setPendingDraft,
    generationAbortRef,
  }
}
