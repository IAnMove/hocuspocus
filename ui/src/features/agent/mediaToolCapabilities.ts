import type { defineCapability } from './capabilityRegistry'

/**
 * The media steps of a production as one Wizard action: a frame of a clip, a
 * still composed from cutouts, an exact cut of a sound, a file from another
 * workspace and a chroma key. They post to /api/v1/media/commands, the same
 * handlers the MCP tools of the same names run, so a file the Wizard makes has
 * the same provenance sidecar as one an agent makes.
 */
export const MEDIA_TOOL_OPERATIONS = [
  'media.frame',
  'media.compose',
  'audio.trim',
  'assets.import_from_workspace',
  'studio.key',
] as const

export type MediaToolOperation = typeof MEDIA_TOOL_OPERATIONS[number]

export interface AgentMediaToolAction {
  type: 'media_tool'
  operation: MediaToolOperation
  input: Record<string, unknown>
}

type MediaReply = {
  result?: { file?: string, url?: string, report?: { haze?: boolean, semiTransparentShare?: number }, already_present?: boolean }
  detail?: { message?: string } | string
}

const operations = new Set<string>(MEDIA_TOOL_OPERATIONS)

export function mediaToolMessage(operation: MediaToolOperation, reply: MediaReply): string {
  const file = reply.result?.file || ''
  const verb: Record<MediaToolOperation, string> = {
    'media.frame': 'Fotograma guardado', 'media.compose': 'Imagen compuesta', 'audio.trim': 'Sonido recortado',
    'assets.import_from_workspace': reply.result?.already_present ? 'Ya estaba en este espacio' : 'Archivo traído',
    'studio.key': 'Fondo quitado',
  }
  const report = reply.result?.report
  const haze = report?.haze
    ? ` Queda un velo en el ${Math.round((report.semiTransparentShare || 0) * 100)} % de la imagen: prueba otra pantalla (mode).`
    : ''
  return `${verb[operation]}: ${file}.${haze}`
}

export async function executeMediaTool(action: AgentMediaToolAction, workspace?: string) {
  const input = { ...action.input, workspace: typeof action.input.workspace === 'string' && action.input.workspace ? action.input.workspace : workspace || '' }
  const response = await fetch('/api/v1/media/commands', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operation: action.operation, version: 1, input }),
  })
  const reply = await response.json() as MediaReply
  if (!response.ok) {
    throw new Error(typeof reply.detail === 'string' ? reply.detail : reply.detail?.message || `${action.operation} failed`)
  }
  return {
    message: mediaToolMessage(action.operation, reply),
    metadata: reply as Record<string, unknown>,
    target: { kind: 'output', id: reply.result?.file || action.operation, title: action.operation },
  }
}

export function registerMediaToolCapabilities(register: typeof defineCapability) {
  register<AgentMediaToolAction>({
    name: 'media_tool',
    title: 'Frames, stills, sound cuts, cross-workspace files and keys',
    description: 'Run one media step in the active workspace and save its file with provenance: media.frame {source video, at: seconds | "first" | "last", output_name} saves a frame as PNG; media.compose {base image or video (base_at), layers: [{file, x, y (% centre), scale (fraction of height), anchor "bottom", flip, rotation, opacity}], output_name} pastes cutouts over a frame; audio.trim {source, start, length | end, output_name} cuts part of a sound exactly; assets.import_from_workspace {source_workspace, file, destination_filename} brings a file (a GLB, image, sound or clip) from another workspace; studio.key {source, mode green|blue|magenta} removes a plain screen (its report says if a haze is left). Use workspace file names the app snapshot shows.',
    useWhen: 'The user asks for a frame of a clip, a start frame made of a frame plus a character, part of a sound, a file from another workspace, or to key out a green/blue/magenta screen.',
    parameters: ['operation', 'input'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: { type: { const: 'media_tool' }, operation: { enum: [...MEDIA_TOOL_OPERATIONS] }, input: { type: 'object' } },
      required: ['type', 'operation', 'input'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Preparando el archivo…',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'media_tool', operation: raw.operation as MediaToolOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose a media tool operation.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.mediaTools.command(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'output', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'images', anchors: ['output'], replay: 'atomic' },
  })
}
