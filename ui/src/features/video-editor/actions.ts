import { fetchOutputs, fetchVideoEditorExport, getVideoEditorThumbnailUrl, probeVideoEditorAudio, probeVideoEditorClip, startVideoEditorExport, type ApiOutput } from '../../api/client'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { useStore } from '../../stores/useStore'
import { clipId, loadEditorDraft, persistEditorDraft, RESOLUTIONS, type EditorSoundtrack } from './editorDraft'
import { sequenceTotalDuration } from './editorTimeline'
import type { EditorClip } from './editorClipNormalization'
import type {
  AddVideoEditorAudioCommand,
  AddVideoEditorClipsCommand,
  CreateVideoEditorProjectCommand,
  ExportVideoEditorCommand,
  OpenVideoEditorProjectCommand,
  OrderVideoEditorClipsCommand,
  TrimVideoEditorClipCommand,
} from './commands'

const EXPORT_KEY = 'maestro-video-editor-export-v1'

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function loadDraft() {
  return loadEditorDraft(workspaceName())
}

function saveDraft(
  clips: EditorClip[],
  projectName: string,
  resolution = loadDraft().resolution,
  fps = loadDraft().fps,
  soundtrack: EditorSoundtrack | null | undefined = undefined,
): void {
  persistEditorDraft(clips, projectName, resolution, fps, workspaceName(), soundtrack)
}

function editorEntity() {
  const draft = loadDraft()
  return { kind: 'video_editor', id: draft.projectName, workspaceId: workspaceName() }
}

function editorResult(extra: Parameters<typeof commandResultFromSlice>[0] = {}): CommandResult {
  const entity = editorEntity()
  return commandResultFromSlice({
    entity,
    navigationTarget: { destination: 'video_editor', entity },
    ...extra,
  })
}

export async function createAgentVideoEditorProject(command: CreateVideoEditorProjectCommand): Promise<CommandResult> {
  const name = command.projectName.trim() || 'my_video'
  saveDraft([], name, RESOLUTIONS[0], 30, null)
  return editorResult()
}

export async function openAgentVideoEditorProject(command: OpenVideoEditorProjectCommand): Promise<CommandResult> {
  const draft = loadDraft()
  if (command.projectName.trim() && draft.projectName !== command.projectName.trim()) {
    throw new Error(
      `There is only one Video Editor draft per workspace: “${draft.projectName}”. `
      + 'Explicitly ask to create another project to replace the current draft.',
    )
  }
  return editorResult()
}

async function clipsFromNamedOutputs(
  names: string[],
  mediaType?: ApiOutput['type'],
): Promise<EditorClip[]> {
  const listed = await fetchOutputs(80, 0, { workspace: workspaceName(), mediaType })
  let fallback: Awaited<ReturnType<typeof fetchOutputs>> | null = null
  const added: EditorClip[] = []
  for (const name of names) {
    let output = listed.outputs.find(item => item.name === name)
    if (!output && mediaType) {
      fallback = fallback || await fetchOutputs(80, 0, { workspace: workspaceName() })
      output = fallback.outputs.find(item => item.name === name)
    }
    if (!output) throw new Error(`There is no output “${name}” in this workspace.`)
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
  return added
}

export async function addAgentVideoEditorClips(command: AddVideoEditorClipsCommand): Promise<CommandResult> {
  const draft = loadDraft()
  const added = await clipsFromNamedOutputs(command.outputNames)
  saveDraft([...draft.clips, ...added], draft.projectName, draft.resolution, draft.fps)
  return editorResult()
}

export async function orderAgentVideoEditorClips(command: OrderVideoEditorClipsCommand): Promise<CommandResult> {
  const draft = loadDraft()
  const byName = new Map(draft.clips.map(clip => [clip.name, clip]))
  const ordered = command.clipNames.map(name => {
    const clip = byName.get(name)
    if (!clip) throw new Error(`The clip “${name}” is not in the timeline.`)
    return clip
  })
  const rest = draft.clips.filter(clip => !command.clipNames.includes(clip.name))
  saveDraft([...ordered, ...rest], draft.projectName, draft.resolution, draft.fps)
  return editorResult()
}

export async function trimAgentVideoEditorClip(command: TrimVideoEditorClipCommand): Promise<CommandResult> {
  const draft = loadDraft()
  const clips = draft.clips.map(clip => {
    if (clip.name !== command.clipName && clip.id !== command.clipName) return clip
    const start = Math.max(0, command.trimStart)
    const end = Math.max(start + 0.05, Math.min(clip.duration || command.trimEnd, command.trimEnd))
    return { ...clip, trimStart: start, trimEnd: end }
  })
  if (!draft.clips.some(clip => clip.name === command.clipName || clip.id === command.clipName)) {
    throw new Error(`I can't find the clip “${command.clipName}” to trim.`)
  }
  saveDraft(clips, draft.projectName, draft.resolution, draft.fps)
  return editorResult()
}

export async function addAgentVideoEditorAudio(command: AddVideoEditorAudioCommand): Promise<CommandResult> {
  const draft = loadDraft()
  const wanted = command.outputName.trim()
  if (!wanted) throw new Error('Give the exact name of the audio output.')
  const outputs = await fetchOutputs(80, 0, { workspace: workspaceName(), mediaType: 'audio' })
  const output = outputs.outputs.find(item => item.name === wanted)
  if (!output) throw new Error(`There is no audio output “${wanted}” in this workspace.`)
  const source = output.url || output.name
  const probe = await probeVideoEditorAudio(source, workspaceName())
  const soundtrack: EditorSoundtrack = {
    name: output.name,
    source,
    duration: probe.duration,
    trimStart: 0,
    trimEnd: probe.duration,
    volume: 1,
    loop: probe.duration < sequenceTotalDuration(draft.clips),
  }
  saveDraft(draft.clips, draft.projectName, draft.resolution, draft.fps, soundtrack)
  return editorResult()
}

export async function validateAgentVideoEditorTimeline(): Promise<CommandResult> {
  const draft = loadDraft()
  if (!draft.clips.length) throw new Error('The timeline is empty.')
  const duration = sequenceTotalDuration(draft.clips)
  if (duration <= 0) throw new Error('The timeline has no usable duration.')
  return editorResult()
}

export async function exportAgentVideoEditor(command: ExportVideoEditorCommand): Promise<CommandResult> {
  if (!command.confirm) throw new Error('Exporting requires confirm=true.')
  const draft = loadDraft()
  if (!draft.clips.length) throw new Error('There are no clips to export.')
  const job = await startVideoEditorExport({
    name: draft.projectName,
    width: draft.resolution.width,
    height: draft.resolution.height,
    fps: draft.fps,
    workspace: workspaceName(),
    soundtrack: draft.soundtrack ? {
      name: draft.soundtrack.name,
      source: draft.soundtrack.source,
      trim_start: draft.soundtrack.trimStart,
      trim_end: draft.soundtrack.trimEnd,
      volume: draft.soundtrack.volume,
      loop: draft.soundtrack.loop,
    } : null,
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
  if (!job.job_id) throw new Error('The exporter returned success without a jobId.')
  try {
    window.localStorage.setItem(`${EXPORT_KEY}:${encodeURIComponent(workspaceName())}`, job.job_id)
  } catch { /* keep going */ }
  return editorResult({
    status: 'queued',
    taskIds: [job.job_id],
  })
}

export async function trackAgentVideoEditorExport(): Promise<CommandResult> {
  let jobId = ''
  try {
    jobId = window.localStorage.getItem(`${EXPORT_KEY}:${encodeURIComponent(workspaceName())}`) || ''
  } catch {
    jobId = ''
  }
  if (!jobId) throw new Error('There is no Video Editor export in progress.')
  const job = await fetchVideoEditorExport(jobId)
  const status = job.status === 'completed' ? 'completed'
    : job.status === 'failed' || job.status === 'cancelled' ? 'failed'
      : 'queued'
  const owner = editorEntity()
  return editorResult({
    status,
    taskIds: [job.job_id],
    artifacts: [{
      id: job.filename || `export-job:${job.job_id}`,
      kind: job.filename ? 'video' : 'document',
      owner,
      taskId: job.job_id,
      uri: job.url || job.filename || job.job_id,
      metadata: { status: job.status, message: job.message || '' },
    }],
  })
}
