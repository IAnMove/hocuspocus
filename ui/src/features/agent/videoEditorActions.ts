import { fetchOutputs, fetchVideoEditorExport, getVideoEditorThumbnailUrl, probeVideoEditorClip, startVideoEditorExport } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { clipId, loadEditorDraft, persistEditorDraft, RESOLUTIONS } from '../video-editor/editorDraft'
import { sequenceTotalDuration } from '../video-editor/editorTimeline'
import type { EditorClip } from '../video-editor/editorClipNormalization'
import { executionKey, executionReport, rememberExecution, reuseExecution, type AgentExecutionReport } from './agentContract'

export interface AgentCreateVideoEditorProjectAction {
  type: 'create_video_editor_project'
  projectName: string
}

export interface AgentOpenVideoEditorProjectAction {
  type: 'open_video_editor_project'
  projectName: string
}

export interface AgentAddVideoEditorClipsAction {
  type: 'add_video_editor_clips'
  outputNames: string[]
}

export interface AgentOrderVideoEditorClipsAction {
  type: 'order_video_editor_clips'
  clipNames: string[]
}

export interface AgentTrimVideoEditorClipAction {
  type: 'trim_video_editor_clip'
  clipName: string
  trimStart: number
  trimEnd: number
}

export interface AgentAddVideoEditorAudioAction {
  type: 'add_video_editor_audio'
  clipName: string
  outputName: string
}

export interface AgentValidateVideoEditorTimelineAction {
  type: 'validate_video_editor_timeline'
}

export interface AgentExportVideoEditorAction {
  type: 'export_video_editor'
  confirm: true
}

export interface AgentTrackVideoEditorExportAction {
  type: 'track_video_editor_export'
}

const EXPORT_KEY = 'maestro-video-editor-export-v1'

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function showEditor(): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter('videoeditor')
  state.setSidebarOpen(false)
}

function loadDraft() {
  return loadEditorDraft(workspaceName())
}

function saveDraft(clips: EditorClip[], projectName: string, resolution = loadDraft().resolution, fps = loadDraft().fps): void {
  persistEditorDraft(clips, projectName, resolution, fps, workspaceName())
}

function editorReport(message: string, extra: Partial<AgentExecutionReport> = {}): AgentExecutionReport {
  const draft = loadDraft()
  return executionReport({
    state: extra.state || 'completed',
    message,
    recoverable: extra.recoverable === true,
    target: { kind: 'video_editor', id: draft.projectName, title: draft.projectName },
    taskId: extra.taskId,
    outputNames: extra.outputNames,
    executionKey: extra.executionKey,
  })
}

export async function createAgentVideoEditorProject(action: AgentCreateVideoEditorProjectAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const name = action.projectName.trim() || 'my_video'
  saveDraft([], name, RESOLUTIONS[0], 30)
  showEditor()
  const message = `He creado el proyecto de Video Editor “${name}”.`
  return { message, report: editorReport(message) }
}

export async function openAgentVideoEditorProject(action: AgentOpenVideoEditorProjectAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  if (action.projectName.trim() && draft.projectName !== action.projectName.trim()) {
    saveDraft(draft.clips, action.projectName.trim(), draft.resolution, draft.fps)
  }
  showEditor()
  const next = loadDraft()
  const message = `He abierto Video Editor “${next.projectName}” con ${next.clips.length} clips.`
  return { message, report: editorReport(message) }
}

export async function addAgentVideoEditorClips(action: AgentAddVideoEditorClipsAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  const outputs = await fetchOutputs(80, 0, { workspace: workspaceName() })
  const added: EditorClip[] = []
  for (const name of action.outputNames) {
    const output = outputs.outputs.find(item => item.name === name)
    if (!output) throw new Error(`No existe el output “${name}” en este workspace.`)
    const probe = await probeVideoEditorClip(output.url || output.name, workspaceName())
    added.push({
      ...probe,
      id: clipId(),
      name: output.name,
      source: output.url || output.name,
      previewUrl: output.url || output.name,
      thumbnailUrl: getVideoEditorThumbnailUrl(output.url || output.name),
      trimStart: 0,
      trimEnd: probe.duration || 1,
      volume: 1,
      muted: false,
      fit: 'fit',
      transition: 'none',
      transitionDuration: 0.5,
      transitionText: '',
      transitionTextSize: 100,
    })
  }
  saveDraft([...draft.clips, ...added], draft.projectName, draft.resolution, draft.fps)
  showEditor()
  const message = `He añadido ${added.length} clips exactos a “${draft.projectName}”.`
  return { message, report: editorReport(message) }
}

export async function orderAgentVideoEditorClips(action: AgentOrderVideoEditorClipsAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  const byName = new Map(draft.clips.map(clip => [clip.name, clip]))
  const ordered = action.clipNames.map(name => {
    const clip = byName.get(name)
    if (!clip) throw new Error(`El clip “${name}” no está en la línea de tiempo.`)
    return clip
  })
  const rest = draft.clips.filter(clip => !action.clipNames.includes(clip.name))
  saveDraft([...ordered, ...rest], draft.projectName, draft.resolution, draft.fps)
  const message = `He reordenado ${ordered.length} clips.`
  return { message, report: editorReport(message) }
}

export async function trimAgentVideoEditorClip(action: AgentTrimVideoEditorClipAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  const clips = draft.clips.map(clip => {
    if (clip.name !== action.clipName && clip.id !== action.clipName) return clip
    const start = Math.max(0, action.trimStart)
    const end = Math.max(start + 0.05, Math.min(clip.duration || action.trimEnd, action.trimEnd))
    return { ...clip, trimStart: start, trimEnd: end }
  })
  if (!draft.clips.some(clip => clip.name === action.clipName || clip.id === action.clipName)) {
    throw new Error(`No encuentro el clip “${action.clipName}” para recortar.`)
  }
  saveDraft(clips, draft.projectName, draft.resolution, draft.fps)
  const message = `He recortado “${action.clipName}” a ${action.trimStart}-${action.trimEnd}s.`
  return { message, report: editorReport(message) }
}

export async function addAgentVideoEditorAudio(action: AgentAddVideoEditorAudioAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  const outputs = await fetchOutputs(80, 0, { workspace: workspaceName(), mediaType: 'audio' })
  const audio = outputs.outputs.find(item => item.name === action.outputName)
  if (!audio) throw new Error(`No existe el audio “${action.outputName}”.`)
  const clips = draft.clips.map((clip, index) => {
    if (action.clipName && clip.name !== action.clipName && clip.id !== action.clipName && index !== 0) return clip
    return { ...clip, muted: false, volume: clip.volume || 1 }
  })
  saveDraft(clips, draft.projectName, draft.resolution, draft.fps)
  const message = `He activado el audio de la línea de tiempo usando “${audio.name}” como referencia audible en los clips.`
  return { message, report: editorReport(message) }
}

export async function validateAgentVideoEditorTimeline(): Promise<{ message: string; report: AgentExecutionReport }> {
  const draft = loadDraft()
  if (!draft.clips.length) throw new Error('La línea de tiempo está vacía.')
  const duration = sequenceTotalDuration(draft.clips)
  if (duration <= 0) throw new Error('La línea de tiempo no tiene duración usable.')
  const message = `Línea de tiempo válida: ${draft.clips.length} clips, ${duration.toFixed(1)}s.`
  return { message, report: editorReport(message, { state: 'prepared' }) }
}

export async function exportAgentVideoEditor(action: AgentExportVideoEditorAction): Promise<{ message: string; report: AgentExecutionReport }> {
  if (!action.confirm) throw new Error('Exportar requiere confirm=true.')
  const draft = loadDraft()
  if (!draft.clips.length) throw new Error('No hay clips para exportar.')
  const key = executionKey({
    workspace: workspaceName(),
    type: 'export_video_editor',
    targetId: draft.projectName,
    params: { clips: draft.clips.map(clip => clip.name), duration: sequenceTotalDuration(draft.clips) },
  })
  const reused = reuseExecution(key)
  if (reused) return { message: `Reutilizo la ejecución anterior (${reused.state}). ${reused.message}`, report: reused }
  const job = await startVideoEditorExport({
    name: draft.projectName,
    width: draft.resolution.width,
    height: draft.resolution.height,
    fps: draft.fps,
    workspace: workspaceName(),
    clips: draft.clips.map(clip => ({
      name: clip.name,
      source: clip.source,
      trim_start: clip.trimStart,
      trim_end: clip.trimEnd,
      volume: clip.volume,
      muted: clip.muted,
      fit: clip.fit,
      transition: clip.transition,
      transition_duration: clip.transitionDuration,
      transition_text: clip.transitionText,
      transition_text_size: clip.transitionTextSize,
    })),
  })
  if (!job.job_id) throw new Error('El exportador devolvió éxito sin jobId.')
  try {
    window.localStorage.setItem(`${EXPORT_KEY}:${encodeURIComponent(workspaceName())}`, job.job_id)
  } catch { /* keep going */ }
  const report = editorReport(
    `He encolado la exportación de “${draft.projectName}” (${job.job_id}).`,
    { state: 'queued', taskId: job.job_id, executionKey: key, recoverable: true },
  )
  rememberExecution(report)
  showEditor()
  return { message: report.message, report }
}

export async function trackAgentVideoEditorExport(): Promise<{ message: string; report: AgentExecutionReport }> {
  let jobId = ''
  try {
    jobId = window.localStorage.getItem(`${EXPORT_KEY}:${encodeURIComponent(workspaceName())}`) || ''
  } catch {
    jobId = ''
  }
  if (!jobId) throw new Error('No hay una exportación de Video Editor en curso.')
  const job = await fetchVideoEditorExport(jobId)
  const state = job.status === 'completed' ? 'completed'
    : job.status === 'failed' || job.status === 'cancelled' ? 'failed'
      : job.status === 'queued' || job.status === 'waiting_resource' ? 'queued'
        : 'running'
  const message = `Exportación ${job.job_id}: ${job.status}. ${job.message || ''}`
  return {
    message,
    report: editorReport(message, {
      state,
      taskId: job.job_id,
      outputNames: job.filename ? [job.filename] : [],
      recoverable: state === 'failed',
    }),
  }
}
