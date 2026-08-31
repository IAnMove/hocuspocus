import {
  attachAlternativeSong,
  fetchAlternativeSongs,
  fetchVideoEditorExport,
  mountAlternativeSong,
} from '../../api/client'
import { useStore } from '../../stores/useStore'
import { executionKey, executionReport, rememberExecution, reuseExecution, type AgentExecutionReport } from './agentContract'

export interface AgentAttachVideoclipAlternativeSongAction {
  type: 'attach_videoclip_alternative_song'
  videoclipName: string
  audioOutputName: string
}

export interface AgentMountVideoclipAlternativeSongAction {
  type: 'mount_videoclip_alternative_song'
  videoclipName: string
  audioOutputName: string
  songId?: string
  confirm: true
}

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function showVideoclips(): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter('videoclips')
}

function songReport(message: string, extra: Partial<AgentExecutionReport> = {}): AgentExecutionReport {
  return executionReport({
    state: extra.state || 'completed',
    message,
    recoverable: extra.recoverable === true,
    target: extra.target || { kind: 'video', id: extra.outputNames?.[0] || 'videoclip', title: extra.outputNames?.[0] || 'videoclip' },
    taskId: extra.taskId,
    outputNames: extra.outputNames,
    executionKey: extra.executionKey,
  })
}

export async function attachAgentVideoclipAlternativeSong(
  action: AgentAttachVideoclipAlternativeSongAction,
): Promise<{ message: string; report: AgentExecutionReport }> {
  const videoclip = action.videoclipName.trim()
  const audio = action.audioOutputName.trim()
  if (!videoclip) throw new Error('Indica el videoclip exacto.')
  if (!audio) throw new Error('Indica el output de audio exacto.')
  const result = await attachAlternativeSong(videoclip, audio, workspaceName())
  showVideoclips()
  const message = `He añadido “${audio}” como canción alternativa de “${videoclip}” (${result.adaptation === 'random_extras' ? 'extras aleatorios si hace falta' : 'se repetirá el videoclip si hace falta'}). Aún no he montado el vídeo.`
  return {
    message,
    report: songReport(message, {
      state: 'prepared',
      target: { kind: 'video', id: videoclip, title: videoclip },
      outputNames: [videoclip],
    }),
  }
}

export async function mountAgentVideoclipAlternativeSong(
  action: AgentMountVideoclipAlternativeSongAction,
): Promise<{ message: string; report: AgentExecutionReport }> {
  if (!action.confirm) throw new Error('Montar una canción alternativa requiere confirm=true.')
  const videoclip = action.videoclipName.trim()
  const audio = action.audioOutputName.trim()
  if (!videoclip) throw new Error('Indica el videoclip exacto.')
  if (!audio && !action.songId) throw new Error('Indica la canción exacta.')
  const key = executionKey({
    workspace: workspaceName(),
    type: 'mount_videoclip_alternative_song',
    targetId: videoclip,
    params: { audio, songId: action.songId || '' },
  })
  const reused = reuseExecution(key)
  if (reused) return { message: `Reutilizo la ejecución anterior (${reused.state}). ${reused.message}`, report: reused }
  let songId = action.songId?.trim() || ''
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
  const report = songReport(
    `Estoy montando “${videoclip}” con “${started.song.audio_name}” (FFmpeg, sin regenerar planos). El resultado será “${started.output_name}”.`,
    {
      state: 'running',
      target: { kind: 'video', id: videoclip, title: videoclip },
      taskId: started.task_id || started.job_id,
      outputNames: [started.output_name],
      executionKey: key,
    },
  )
  rememberExecution(report)
  return { message: report.message, report }
}

export async function trackAgentVideoclipAlternativeSong(
  videoclipName: string,
): Promise<{ message: string; report: AgentExecutionReport }> {
  const list = await fetchAlternativeSongs(videoclipName, workspaceName())
  const mounting = list.songs.find(song => song.status === 'mounting' && song.job_id)
  if (mounting?.job_id) {
    const job = await fetchVideoEditorExport(mounting.job_id)
    const message = job.status === 'completed'
      ? `El montaje de “${mounting.audio_name}” terminó: ${job.filename || mounting.mounted_output}.`
      : `El montaje de “${mounting.audio_name}” está ${job.status}: ${job.message}`
    return {
      message,
      report: songReport(message, {
        state: job.status === 'completed' ? 'completed' : job.status === 'failed' || job.status === 'cancelled' ? 'failed' : 'running',
        taskId: job.task_id || job.job_id,
        outputNames: job.filename ? [job.filename] : [],
        target: { kind: 'video', id: videoclipName, title: videoclipName },
      }),
    }
  }
  const mounted = [...list.songs].reverse().find(song => song.status === 'mounted' && song.mounted_output)
  if (mounted?.mounted_output) {
    const message = `La última canción alternativa montada es “${mounted.audio_name}” → “${mounted.mounted_output}”.`
    return {
      message,
      report: songReport(message, {
        outputNames: [mounted.mounted_output],
        target: { kind: 'video', id: videoclipName, title: videoclipName },
      }),
    }
  }
  const message = list.songs.length
    ? `“${videoclipName}” tiene ${list.songs.length} canciones alternativas adjuntas y ninguna se está montando.`
    : `“${videoclipName}” no tiene canciones alternativas todavía.`
  return { message, report: songReport(message, { state: 'prepared', target: { kind: 'video', id: videoclipName, title: videoclipName } }) }
}
