import {
  attachAlternativeSong,
  fetchAlternativeSongs,
  fetchVideoEditorExport,
  mountAlternativeSong,
} from '../../api/client'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
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
  if (!videoclip) throw new Error('Indica el videoclip exacto.')
  if (!audio) throw new Error('Indica el output de audio exacto.')
  const result = await attachAlternativeSong(videoclip, audio, workspaceName())
  showVideoclips()
  return songResult(
    videoclip,
    `He añadido “${audio}” como canción alternativa de “${videoclip}” (${result.adaptation === 'random_extras' ? 'extras aleatorios si hace falta' : 'se repetirá el videoclip si hace falta'}). Aún no he montado el vídeo.`,
    { state: 'prepared' },
  )
}

export async function mountSong(command: MountAlternativeSongCommand): Promise<CommandResult> {
  if (!command.confirm) throw new Error('Montar una canción alternativa requiere confirm=true.')
  const videoclip = command.videoclipName.trim()
  const audio = command.audioOutputName.trim()
  if (!videoclip) throw new Error('Indica el videoclip exacto.')
  if (!audio && !command.songId) throw new Error('Indica la canción exacta.')
  let songId = command.songId?.trim() || ''
  if (!songId) {
    const attached = await attachAlternativeSong(videoclip, audio, workspaceName())
    const song = attached.song || attached.songs.find(item => item.audio_name === audio)
    if (!song) throw new Error('No pude adjuntar la canción alternativa.')
    songId = song.id
  }
  const started = await mountAlternativeSong(videoclip, songId, {
    audioName: audio || undefined,
    workspace: workspaceName(),
  })
  showVideoclips()
  return songResult(
    videoclip,
    `Estoy montando “${videoclip}” con “${started.song.audio_name}” (FFmpeg, sin regenerar planos). El resultado será “${started.output_name}”.`,
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
    const message = job.status === 'completed'
      ? `El montaje de “${mounting.audio_name}” terminó: ${job.filename || mounting.mounted_output}.`
      : `El montaje de “${mounting.audio_name}” está ${job.status}: ${job.message}`
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
      `La última canción alternativa montada es “${mounted.audio_name}” → “${mounted.mounted_output}”.`,
      { outputName: mounted.mounted_output },
    )
  }
  const message = list.songs.length
    ? `“${videoclipName}” tiene ${list.songs.length} canciones alternativas adjuntas y ninguna se está montando.`
    : `“${videoclipName}” no tiene canciones alternativas todavía.`
  return songResult(videoclipName, message, { state: 'prepared' })
}
