import {
  attachAlternativeSong,
  fetchAlternativeSongs,
  fetchVideoEditorExport,
  mountAlternativeSong,
} from '../../api/client'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import i18n from '../../i18n'
import { useStore } from '../../stores/useStore'
import type {
  AttachAlternativeSongCommand,
  MountAlternativeSongCommand,
  TrackAlternativeSongCommand,
} from './commands'

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function showVideoclips(): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter('videoclips')
}

function songResult(
  videoclip: string,
  message: string,
  extra: { taskId?: string; outputName?: string; state?: string } = {},
): CommandResult {
  const entity = { kind: 'video', id: videoclip, workspaceId: workspaceName() }
  return commandResultFromSlice({
    entity,
    taskIds: extra.taskId ? [extra.taskId] : undefined,
    artifacts: [{
      id: extra.outputName || 'reply',
      kind: extra.outputName ? 'video' : 'document',
      owner: entity,
      uri: extra.outputName || 'videoclips:reply',
      metadata: {
        summary: message,
        title: videoclip,
        state: extra.state || 'completed',
        outputName: extra.outputName,
      },
    }],
  })
}

export async function attachSong(command: AttachAlternativeSongCommand): Promise<CommandResult> {
  const videoclip = command.videoclipName.trim()
  const audio = command.audioOutputName.trim()
  if (!videoclip) throw new Error(i18n.t('videoEditor:actionErrors.videoclipRequired'))
  if (!audio) throw new Error(i18n.t('videoEditor:actionErrors.videoclipAudioRequired'))
  const result = await attachAlternativeSong(videoclip, audio, workspaceName())
  showVideoclips()
  const adaptation = result.adaptation === 'random_extras'
    ? i18n.t('videoEditor:replies.videoclipAdaptationRandom')
    : i18n.t('videoEditor:replies.videoclipAdaptationRepeat')
  return songResult(
    videoclip,
    i18n.t('videoEditor:replies.videoclipAdded', { audio, videoclip, adaptation }),
    { state: 'prepared' },
  )
}

export async function mountSong(command: MountAlternativeSongCommand): Promise<CommandResult> {
  if (!command.confirm) throw new Error(i18n.t('videoEditor:actionErrors.videoclipMountConfirm'))
  const videoclip = command.videoclipName.trim()
  const audio = command.audioOutputName.trim()
  if (!videoclip) throw new Error(i18n.t('videoEditor:actionErrors.videoclipRequired'))
  if (!audio && !command.songId) throw new Error(i18n.t('videoEditor:actionErrors.videoclipSongRequired'))
  let songId = command.songId?.trim() || ''
  if (!songId) {
    const attached = await attachAlternativeSong(videoclip, audio, workspaceName())
    const song = attached.song || attached.songs.find(item => item.audio_name === audio)
    if (!song) throw new Error(i18n.t('videoEditor:actionErrors.videoclipAttachFailed'))
    songId = song.id
  }
  const started = await mountAlternativeSong(videoclip, songId, {
    audioName: audio || undefined,
    workspace: workspaceName(),
  })
  showVideoclips()
  return songResult(
    videoclip,
    i18n.t('videoEditor:replies.videoclipMounting', {
      videoclip,
      audio: started.song.audio_name,
      output: started.output_name,
    }),
    {
      state: 'running',
      taskId: started.task_id || started.job_id,
      outputName: started.output_name,
    },
  )
}

export async function trackSong(command: TrackAlternativeSongCommand): Promise<CommandResult> {
  const videoclipName = command.videoclipName.trim()
  const list = await fetchAlternativeSongs(videoclipName, workspaceName())
  const mounting = list.songs.find(song => song.status === 'mounting' && song.job_id)
  if (mounting?.job_id) {
    const job = await fetchVideoEditorExport(mounting.job_id)
    const output = job.filename || mounting.mounted_output
    const message = job.status === 'completed'
      ? i18n.t('videoEditor:replies.videoclipMountFinished', { audio: mounting.audio_name, output })
      : i18n.t('videoEditor:replies.videoclipMountStatus', { audio: mounting.audio_name, status: job.status, message: job.message })
    const failed = job.status === 'failed' || job.status === 'cancelled'
    return songResult(videoclipName, message, {
      state: job.status === 'completed' ? 'completed' : failed ? 'failed' : 'running',
      taskId: job.task_id || job.job_id,
      outputName: job.filename || undefined,
    })
  }
  const mounted = [...list.songs].reverse().find(song => song.status === 'mounted' && song.mounted_output)
  if (mounted?.mounted_output) {
    return songResult(
      videoclipName,
      i18n.t('videoEditor:replies.videoclipLastMounted', { audio: mounted.audio_name, output: mounted.mounted_output }),
      { outputName: mounted.mounted_output },
    )
  }
  const message = list.songs.length
    ? i18n.t('videoEditor:replies.videoclipAlternativesAttached', { name: videoclipName, total: list.songs.length })
    : i18n.t('videoEditor:replies.videoclipNoAlternatives', { name: videoclipName })
  return songResult(videoclipName, message, { state: 'prepared' })
}
