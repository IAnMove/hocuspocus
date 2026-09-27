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
  if (!videoclip) throw new Error('Give the exact music video.')
  if (!audio) throw new Error('Give the exact audio output.')
  const result = await attachAlternativeSong(videoclip, audio, workspaceName())
  showVideoclips()
  return songResult(
    videoclip,
    `I added “${audio}” as an alternative song for “${videoclip}” (${result.adaptation === 'random_extras' ? 'random extras if needed' : 'the music video will repeat if needed'}). I have not assembled the video yet.`,
    { state: 'prepared' },
  )
}

export async function mountSong(command: MountAlternativeSongCommand): Promise<CommandResult> {
  if (!command.confirm) throw new Error('Assembling an alternative song requires confirm=true.')
  const videoclip = command.videoclipName.trim()
  const audio = command.audioOutputName.trim()
  if (!videoclip) throw new Error('Give the exact music video.')
  if (!audio && !command.songId) throw new Error('Give the exact song.')
  let songId = command.songId?.trim() || ''
  if (!songId) {
    const attached = await attachAlternativeSong(videoclip, audio, workspaceName())
    const song = attached.song || attached.songs.find(item => item.audio_name === audio)
    if (!song) throw new Error('I couldn\'t attach the alternative song.')
    songId = song.id
  }
  const started = await mountAlternativeSong(videoclip, songId, {
    audioName: audio || undefined,
    workspace: workspaceName(),
  })
  showVideoclips()
  return songResult(
    videoclip,
    `Assembling “${videoclip}” with “${started.song.audio_name}” (FFmpeg, without regenerating shots). The result will be “${started.output_name}”.`,
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
      ? `The assembly with “${mounting.audio_name}” finished: ${job.filename || mounting.mounted_output}.`
      : `The assembly with “${mounting.audio_name}” is ${job.status}: ${job.message}`
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
      `The last assembled alternative song is “${mounted.audio_name}” → “${mounted.mounted_output}”.`,
      { outputName: mounted.mounted_output },
    )
  }
  const message = list.songs.length
    ? `“${videoclipName}” has ${list.songs.length} alternative songs attached and none is being assembled.`
    : `“${videoclipName}” has no alternative songs yet.`
  return songResult(videoclipName, message, { state: 'prepared' })
}
