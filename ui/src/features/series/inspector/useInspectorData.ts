import { useCallback, useEffect, useState } from 'react'
import { fetchCharacterKitLibrary } from '../../../api/characters'
import {
  fetchShotFiles, fetchShotVoiceJob, fetchShotVoices, fetchSeriesShotView, startShotVoice,
  type SeriesLineVoice, type SeriesLineVoiceJob, type SeriesShotFileKind, type SeriesShotView,
} from '../../../api/seriesShotInspector'
import type { CharacterKitLibrary } from '../../../lib/characterKit'

const POLL_MS = 1500
const TERMINAL = new Set(['completed', 'failed', 'interrupted'])

/** The shot as series.shot.get reads it (the script its sections edit); `replace` takes an edit's reply. */
export function useShotView(workspace: string, seriesId: string, episodeId: string, shotId: string, revision: number) {
  const [view, setView] = useState<SeriesShotView>()
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    fetchSeriesShotView(workspace, seriesId, episodeId, shotId)
      .then(value => { if (alive) { setView(value); setError('') } })
      .catch(reason => { if (alive) setError((reason as Error).message) })
    return () => { alive = false }
  }, [workspace, seriesId, episodeId, shotId, revision])
  const current = view?.shotId === shotId ? view : undefined
  return { view: current, error, replace: setView }
}

/** Each line's recording, and one line recorded (or retaken) now, followed until it is done. */
export function useLineVoices(workspace: string, seriesId: string, episodeId: string, shotId: string) {
  const [voices, setVoices] = useState<{ shotId: string; language: string; lines: SeriesLineVoice[] }>()
  const [jobs, setJobs] = useState<Record<string, SeriesLineVoiceJob>>({})
  const [error, setError] = useState('')
  const [generation, setGeneration] = useState(0)
  const refresh = useCallback(() => setGeneration(value => value + 1), [])
  useEffect(() => {
    let alive = true
    fetchShotVoices(workspace, seriesId, episodeId, shotId).then(value => {
      if (!alive) return
      setVoices(value); setError('')
      if (value.recording.length) setJobs(current => ({ ...current, ...Object.fromEntries(value.recording.map(job => [job.beatId, job])) }))
    }).catch(reason => { if (alive) setError((reason as Error).message) })
    return () => { alive = false }
  }, [workspace, seriesId, episodeId, shotId, generation])
  const live = Object.values(jobs).filter(job => job.shotId === shotId && !TERMINAL.has(job.status))
  const liveIds = live.map(job => job.jobId).join(',')
  useEffect(() => {
    if (!liveIds) return
    const timer = window.setInterval(() => {
      for (const id of liveIds.split(',')) {
        fetchShotVoiceJob(workspace, id).then(job => {
          setJobs(current => ({ ...current, [job.beatId]: job }))
          if (TERMINAL.has(job.status)) refresh()
        }).catch(reason => setError((reason as Error).message))
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [liveIds, workspace, refresh])
  const record = useCallback(async (beatId: string, retake: boolean) => {
    setError('')
    try {
      const job = await startShotVoice(workspace, seriesId, episodeId, shotId, beatId, retake)
      setJobs(current => ({ ...current, [beatId]: job }))
    } catch (reason) { setError((reason as Error).message) }
  }, [workspace, seriesId, episodeId, shotId])
  const shown = voices?.shotId === shotId ? voices : undefined
  return { voices: shown?.lines || [], language: shown?.language, jobs, error, record, refresh, recording: live.length > 0 }
}

const kitCache = new Map<string, Promise<CharacterKitLibrary>>()

/** The workspace's Character Kits (poses for the cast pickers), read once per workspace while the page is open. */
export function useKitLibrary(workspace: string) {
  const [library, setLibrary] = useState<{ workspace: string; value: CharacterKitLibrary }>()
  useEffect(() => {
    let alive = true
    if (!kitCache.has(workspace)) kitCache.set(workspace, fetchCharacterKitLibrary(workspace))
    kitCache.get(workspace)!.then(value => { if (alive) setLibrary({ workspace, value }) }).catch(() => { kitCache.delete(workspace) })
    return () => { alive = false }
  }, [workspace])
  return library?.workspace === workspace ? library.value : null
}

/** Forget the kits read so far (a kit saved in the Characters tool shows its new poses). */
export function forgetKitLibrary(workspace: string) { kitCache.delete(workspace) }

const fileCache = new Map<string, Promise<string[]>>()

/** Workspace files of a kind for a picker's suggestions; the server checks the name on save. */
export function useShotFiles(workspace: string, seriesId: string, kind: SeriesShotFileKind) {
  const [files, setFiles] = useState<{ key: string; value: string[] }>()
  const key = `${workspace}:${seriesId}:${kind}`
  useEffect(() => {
    let alive = true
    if (!fileCache.has(key)) fileCache.set(key, fetchShotFiles(workspace, seriesId, kind).then(value => value.files))
    fileCache.get(key)!.then(value => { if (alive) setFiles({ key, value }) }).catch(() => { fileCache.delete(key) })
    return () => { alive = false }
  }, [workspace, seriesId, kind, key])
  return files?.key === key ? files.value : []
}
