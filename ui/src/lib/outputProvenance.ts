import type { OutputMetadata } from '../types'

/** Who asked for an output: an MCP client (``agent``) or Ask to the Wizard (``wizard``), and with which tool. */
export interface OutputMaker {
  origin: 'agent' | 'wizard'
  capability: string
}

export interface OutputProvenance {
  maker: OutputMaker | null
  /** Music style (ACE-Step caption). */
  style: string
  /** Speech: the designed voice or preset and its instructions. */
  voice: string
  /** Speech cloned from a reference recording (its file name). */
  voiceReference: string
  /** Speech language. */
  language: string
  /** The tool that made the file from others (``studio.key``, ``audio.shorten``, ``characters.rig.flat``, ``media.frame``). */
  tool: string
  /** The files it was made from (``lineage.parents``). */
  parents: string[]
  /** The saved scene document an export rendered (``params.scene_file``). */
  sceneFile: string
  /** The saved montage a Video Editor export was made from (``params.video_editor.montage``). */
  montageFile: string
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' && value !== 'None' ? value.trim() : ''
}

function basename(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).pop() || value
}

export function outputMaker(metadata: OutputMetadata | Record<string, unknown> | undefined | null): OutputMaker | null {
  const data = record(metadata)
  const origin = record(data.origin)
  const requested = record(data.requested_by)
  const capability = text(requested.capability) || text(origin.capability)
  if (origin.actor === 'wizard' || origin.tool === 'wizard' || requested.tool === 'wizard') return { origin: 'wizard', capability }
  if (requested.tool === 'external_agent' || origin.tool === 'external_agent' || origin.actor === 'agent') {
    return { origin: 'agent', capability }
  }
  return null
}

function audioMode(params: Record<string, unknown>): string {
  const recorded = text(params._audio_sub_mode)
  if (recorded) return recorded
  const model = text(params.model_type).toLowerCase()
  if (/ace|song|music/.test(model)) return 'music'
  if (/tts|speech|voice/.test(model)) return 'speech'
  return ''
}

function speechVoice(params: Record<string, unknown>, uploads: Record<string, unknown>): Pick<OutputProvenance, 'voice' | 'voiceReference' | 'language'> {
  const reference = text(uploads.audio_guide) || text(params.audio_guide)
  const instructions = text(params.alt_prompt)
  const mode = text(params.model_mode)
  if (reference) return { voice: '', voiceReference: basename(reference), language: mode }
  if (/voicedesign/i.test(text(params.model_type))) return { voice: instructions, voiceReference: '', language: mode }
  return { voice: [mode, instructions].filter(Boolean).join(' · '), voiceReference: '', language: '' }
}

/** The provenance the gallery details show beside the prompt: maker, audio style or voice, tool, sources, links. Pure. */
export function outputProvenance(metadata: OutputMetadata | Record<string, unknown> | undefined | null): OutputProvenance {
  const data = record(metadata)
  const params = record(data.params)
  const lineage = record(data.lineage)
  const mode = audioMode(params)
  const voice = mode === 'speech' ? speechVoice(params, record(data.upload_filenames)) : { voice: '', voiceReference: '', language: '' }
  const parents = (Array.isArray(lineage.parents) ? lineage.parents : [])
    .map(item => text(record(item).uri)).filter(Boolean).slice(0, 8)
  const montage = record(record(params.video_editor).montage)
  // Tool sidecars (studio.key, audio.shorten, the flat rig, the media tools) name the tool on their transformation.
  const transformation = record((Array.isArray(lineage.transformations) ? lineage.transformations : [])[0])
  return {
    maker: outputMaker(data),
    style: mode === 'music' ? text(params.alt_prompt) || text(params.music_description) : '',
    ...voice,
    tool: text(transformation.tool),
    parents,
    sceneFile: text(params.scene_file),
    montageFile: text(montage.file),
  }
}
