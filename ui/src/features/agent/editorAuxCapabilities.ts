import type { AgentGenerateComicPanelAction } from './agentActions'
import type { defineCapability } from './capabilityRegistry'
import type {
  AgentAddVideoEditorAudioAction,
  AgentAddVideoEditorClipsAction,
  AgentExportVideoEditorAction,
  AgentOrderVideoEditorClipsAction,
  AgentTrackVideoEditorExportAction,
  AgentTrimVideoEditorClipAction,
  AgentValidateVideoEditorTimelineAction,
} from './videoEditorActions'
import type { AgentUpdateCharacterKitAction } from './characterKitActions'

/**
 * Capabilities whose executors already live in a lab/action module.
 *
 * The registry owns the canonical definition map, so this file deliberately
 * receives its registrar instead of importing the runtime registrar. That
 * keeps the module safe to load while capabilityRegistry is initializing.
 */

const registeredRegistrars = new WeakSet<object>()

function text(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function stringArray(value: unknown, maxItems: number, maxLength: number): string[] {
  if (!Array.isArray(value)) return []
  return value
    .slice(0, maxItems)
    .flatMap(item => {
      const value = text(item, maxLength)
      return value ? [value] : []
    })
}

function boundedNumber(value: unknown, minimum: number, maximum: number, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(maximum, Math.max(minimum, parsed))
}

export function registerEditorAuxCapabilities(register: typeof defineCapability): void {
  const registrar = register as unknown as object
  if (registeredRegistrars.has(registrar)) return
  registeredRegistrars.add(registrar)

  register<AgentGenerateComicPanelAction>({
    name: 'generate_comic_panel',
    title: 'Regenerate one comic panel',
    description: 'Generate only one addressed panel of the open Comics Director plan.',
    useWhen: 'The user explicitly asks to generate or regenerate a numbered comic panel.',
    parameters: ['page_number', 'panel_number', 'confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'generate_comic_panel' },
        page_number: { type: 'integer', minimum: 1, maximum: 10_000 },
        panel_number: { type: 'integer', minimum: 1, maximum: 10_000 },
        confirm: { const: true },
      },
      required: ['type', 'page_number', 'panel_number', 'confirm'],
    },
    risk: 'compute',
    confirmation: 'required',
    progress: 'Regenerando la viñeta del cómic…',
    resolve(raw) {
      if (raw.confirm !== true) return null
      const pageNumber = typeof raw.page_number === 'number' && Number.isFinite(raw.page_number) && raw.page_number > 0
        ? Math.round(Math.min(10_000, Math.max(1, raw.page_number)))
        : 0
      const panelNumber = typeof raw.panel_number === 'number' && Number.isFinite(raw.panel_number) && raw.panel_number > 0
        ? Math.round(Math.min(10_000, Math.max(1, raw.panel_number)))
        : 0
      return pageNumber && panelNumber
        ? { type: 'generate_comic_panel', pageNumber, panelNumber, confirm: true }
        : null
    },
    validate(action) {
      return action.confirm === true
        && Number.isInteger(action.pageNumber) && action.pageNumber >= 1 && action.pageNumber <= 10_000
        && Number.isInteger(action.panelNumber) && action.panelNumber >= 1 && action.panelNumber <= 10_000
        ? []
        : ['page and panel numbers plus confirmation are required']
    },
    async prepare(action) { return action },
    async execute(action) {
      const [{ generateComicPanelArtwork }, { useComicStore }] = await Promise.all([
        import('./labActions'),
        import('../comics/store'),
      ])
      const message = await generateComicPanelArtwork(action.pageNumber, action.panelNumber)
      const project = useComicStore.getState().project
      return {
        message,
        target: { kind: 'comic', id: project.id, title: project.title },
      }
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'comic', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'comics', anchors: ['panel'], replay: 'atomic' },
  })

  register<AgentUpdateCharacterKitAction>({
    name: 'update_character_kit',
    title: 'Update Character Kit identity',
    description: 'Update the name, visual notes and style of one canonical Character Kit.',
    useWhen: 'The user describes a Character Kit identity, wardrobe or visual style to change.',
    parameters: ['kit_name', 'title', 'look_notes', 'visual_style'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'update_character_kit' },
        kit_name: { type: 'string', maxLength: 160 },
        title: { type: 'string', maxLength: 160 },
        look_notes: { type: 'string', maxLength: 4_000 },
        visual_style: { type: 'string', enum: ['', 'cutout', 'children-illustration', 'anime-2d'] },
      },
      required: ['type'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Actualizando la identidad del Character Kit…',
    resolve(raw) {
      const style = text(raw.visual_style, 40)
      return {
        type: 'update_character_kit',
        kitName: text(raw.kit_name, 160),
        name: text(raw.title, 160),
        lookNotes: text(raw.look_notes, 4_000),
        style: style === 'cutout' || style === 'children-illustration' || style === 'anime-2d' ? style : '',
      }
    },
    validate(action) {
      return action.kitName || action.name || action.lookNotes || action.style
        ? []
        : ['at least one Character Kit field is required']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.characterKit.update(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'character_kit', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'character_kit', anchors: ['kit', 'identity'], replay: 'atomic' },
  })

  register<AgentAddVideoEditorClipsAction>({
    name: 'add_video_editor_clips',
    title: 'Add exact outputs to Video Editor',
    description: 'Add existing workspace outputs as timeline clips in the requested order.',
    useWhen: 'The user names existing generated videos to place on the Video Editor timeline.',
    parameters: ['reference_output_names'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'add_video_editor_clips' },
        reference_output_names: { type: 'array', minItems: 1, maxItems: 24, items: { type: 'string', maxLength: 300 } },
      },
      required: ['type', 'reference_output_names'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Añadiendo clips al Video Editor…',
    resolve(raw) {
      const outputNames = stringArray(raw.reference_output_names, 24, 300)
      return outputNames.length ? { type: 'add_video_editor_clips', outputNames } : null
    },
    validate(action) { return action.outputNames.length ? [] : ['at least one output is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.videoEditor.addClips(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline', 'clips'], replay: 'atomic' },
  })

  register<AgentOrderVideoEditorClipsAction>({
    name: 'order_video_editor_clips',
    title: 'Order Video Editor clips',
    description: 'Reorder the current Video Editor timeline by exact clip names.',
    useWhen: 'The user specifies the order of clips already on the Video Editor timeline.',
    parameters: ['clip_names'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'order_video_editor_clips' },
        clip_names: { type: 'array', minItems: 1, maxItems: 40, items: { type: 'string', maxLength: 300 } },
      },
      required: ['type', 'clip_names'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Reordenando los clips del Video Editor…',
    resolve(raw) {
      const clipNames = stringArray(raw.clip_names, 40, 300)
      return clipNames.length ? { type: 'order_video_editor_clips', clipNames } : null
    },
    validate(action) { return action.clipNames.length ? [] : ['at least one clip is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.videoEditor.orderClips(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline'], replay: 'atomic' },
  })

  register<AgentTrimVideoEditorClipAction>({
    name: 'trim_video_editor_clip',
    title: 'Trim a Video Editor clip',
    description: 'Set trim_start and trim_end on one exact Video Editor clip.',
    useWhen: 'The user asks to cut or trim a named Video Editor clip.',
    parameters: ['clip_name', 'trim_start', 'trim_end'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'trim_video_editor_clip' },
        clip_name: { type: 'string', maxLength: 300 },
        trim_start: { type: 'number', minimum: 0, maximum: 86_400 },
        trim_end: { type: 'number', minimum: 0, maximum: 86_400 },
      },
      required: ['type', 'clip_name', 'trim_end'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Recortando el clip del Video Editor…',
    resolve(raw) {
      const clipName = text(raw.clip_name, 300)
      if (!clipName || typeof raw.trim_end !== 'number' || !Number.isFinite(raw.trim_end)) return null
      const trimEndRaw = raw.trim_end
      const trimStart = boundedNumber(raw.trim_start, 0, 86_400, 0)
      const trimEnd = boundedNumber(trimEndRaw, 0, 86_400, 0)
      if (trimEnd < trimStart + 0.05) return null
      return {
        type: 'trim_video_editor_clip',
        clipName,
        trimStart,
        trimEnd,
      }
    },
    validate(action) {
      return action.clipName && action.trimEnd >= action.trimStart + 0.05
        ? []
        : ['clip name and a usable trim range are required']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.videoEditor.trimClip(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline', 'clip'], replay: 'atomic' },
  })

  register<AgentAddVideoEditorAudioAction>({
    name: 'add_video_editor_audio',
    title: 'Add audio to Video Editor',
    description: 'Probe one exact workspace audio output and set it as the timeline soundtrack.',
    useWhen: 'The user asks to add music or a soundtrack to the Video Editor project.',
    parameters: ['audio_output_name', 'clip_name'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'add_video_editor_audio' },
        audio_output_name: { type: 'string', maxLength: 300 },
        clip_name: { type: 'string', maxLength: 300 },
      },
      required: ['type', 'audio_output_name'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Añadiendo la banda sonora al Video Editor…',
    resolve(raw) {
      const outputName = text(raw.audio_output_name, 300)
      return outputName
        ? { type: 'add_video_editor_audio', clipName: text(raw.clip_name, 300), outputName }
        : null
    },
    validate(action) { return action.outputName ? [] : ['audio output name is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.videoEditor.addAudio(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline', 'audio'], replay: 'atomic' },
  })

  register<AgentValidateVideoEditorTimelineAction>({
    name: 'validate_video_editor_timeline',
    title: 'Validate Video Editor timeline',
    description: 'Check that the current timeline contains clips with usable duration.',
    useWhen: 'The user asks whether the Video Editor timeline is ready to export.',
    parameters: [],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: { type: { const: 'validate_video_editor_timeline' } },
      required: ['type'],
    },
    risk: 'read',
    confirmation: 'none',
    progress: 'Validando la línea de tiempo del Video Editor…',
    resolve() { return { type: 'validate_video_editor_timeline' } },
    validate() { return [] },
    async prepare(action) { return action },
    async execute(_action, context) {
      return context.adapters.videoEditor.validateTimeline()
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'prepared' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline'], replay: 'atomic' },
  })

  register<AgentExportVideoEditorAction>({
    name: 'export_video_editor',
    title: 'Export Video Editor timeline',
    description: 'Start the canonical Video Editor export after explicit confirmation.',
    useWhen: 'The user explicitly asks to export, render or download the edited video.',
    parameters: ['confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: { type: { const: 'export_video_editor' }, confirm: { const: true } },
      required: ['type', 'confirm'],
    },
    risk: 'compute',
    confirmation: 'required',
    progress: 'Encolando la exportación del Video Editor…',
    resolve(raw) { return raw.confirm === true ? { type: 'export_video_editor', confirm: true } : null },
    validate(action) { return action.confirm === true ? [] : ['export confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.videoEditor.exportProject(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline', 'export'], replay: 'atomic' },
  })

  register<AgentTrackVideoEditorExportAction>({
    name: 'track_video_editor_export',
    title: 'Track Video Editor export',
    description: 'Read the latest Video Editor export status and output name.',
    useWhen: 'The user asks how the Video Editor export is progressing.',
    parameters: [],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: { type: { const: 'track_video_editor_export' } },
      required: ['type'],
    },
    risk: 'read',
    confirmation: 'none',
    progress: 'Consultando la exportación del Video Editor…',
    resolve() { return { type: 'track_video_editor_export' } },
    validate() { return [] },
    async prepare(action) { return action },
    async execute(_action, context) {
      return context.adapters.videoEditor.trackExport()
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_editor', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_editor', anchors: ['timeline', 'export'], replay: 'atomic' },
  })
}
