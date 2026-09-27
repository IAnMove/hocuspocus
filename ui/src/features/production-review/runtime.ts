import { BASE } from '../../api/http'
import type { SavedPipelineState } from '../../types'
import { fetchSavedPipeline, rerunClipVideo } from '../../api/director'
import { probeVideoEditorClip, startVideoEditorExport } from '../../api/video-editor'
import { projectReviewDesk } from './project'
import type { ExportSelection, PersistCommand, RegenOutcome, RegenPlan, ReviewDesk } from './types'

export const reviewFileUrl = (name: string, workspace: string) =>
  `/api/v1/file/${encodeURIComponent(name)}?workspace=${encodeURIComponent(workspace)}`

export async function persistReview(desk: ReviewDesk, commands: PersistCommand[]): Promise<SavedPipelineState> {
  const decisions = commands.filter(command => command.type !== 'rerun_clip')
  const response = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(desk.pipelineId)}/review`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace: desk.workspace, commands: decisions }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Could not save review')
  }
  const saved: SavedPipelineState = await response.json()
  if (saved.pipeline_id !== desk.pipelineId) throw new Error('Saved review belongs to another production')
  return saved
}

export async function regenerateReview(desk: ReviewDesk, plan: RegenPlan): Promise<RegenOutcome[]> {
  const outcomes: RegenOutcome[] = []
  for (const job of plan.jobs) {
    try {
      const result = await rerunClipVideo(desk.pipelineId, job.clipIndex, job.prompt)
      const pipeline = await fetchSavedPipeline(desk.pipelineId)
      const actual = projectReviewDesk({ pipeline: { ...pipeline, workspace: desk.workspace } })
      const take = actual.shots.find(shot => shot.clipIndex === job.clipIndex)?.takes.find(item => item.filename === result.filename)
      if (!take) throw new Error('Generated take was not found in the saved production')
      outcomes.push({ shotId: job.shotId, ok: true, take })
    } catch (error) {
      outcomes.push({ shotId: job.shotId, ok: false, error: error instanceof Error ? error.message : String(error) })
    }
  }
  return outcomes
}

export async function exportReview(desk: ReviewDesk, selection: ExportSelection) {
  if (!selection.clips.length) throw new Error('No approved takes to export')
  const sources = await Promise.all(selection.clips.map(async clip => {
    const source = reviewFileUrl(clip.filename, desk.workspace)
    return { clip, source, probe: await probeVideoEditorClip(source, desk.workspace) }
  }))
  const format = sources[0].probe
  return startVideoEditorExport({
    name: `${desk.pipelineId}-approved`, workspace: desk.workspace,
    width: format.width, height: format.height, fps: format.fps,
    clips: sources.map(({ clip, source, probe }) => ({
      name: clip.filename, source, trim_start: 0, trim_end: probe.duration,
      volume: 1, muted: false, fit: 'fit', transition: 'none',
      transition_duration: 0, transition_text: '', transition_text_size: 32,
    })),
  })
}
