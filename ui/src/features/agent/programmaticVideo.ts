import type { AgentTurn } from './agentActions'
import type { defineCapability } from './capabilityRegistry'
import type { SceneGenerationPolicy } from '../../lib/sceneGenerationPolicy'

export interface AgentPrepareProgrammaticVideoAction {
  type: 'prepare_programmatic_video'
  intent: string
  /** Caller authority is derived from the real request, not the model response. */
  generationPolicy: Exclude<SceneGenerationPolicy, 'auto'>
  outputNames: string[]
  sceneCommand?: import('../sceneFx/wizard').ScenePreparationCommand
}

const normalize = (text: string) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
const VIDEO_CONTEXT = /\b(video|videos|videoclip|videoclips|escena|escenas|scene|scenes|clip|clips|compositor|video3d)\b/
const PROGRAMMATIC = /\b(video\s*3d|compositor|programmatic|programatico|programatica|sin video (?:ia|generativo)|without (?:ai|generative) video|no generative video)\b|\b(?:sin|no uses?|no utilices?|without)\s+(?:generadores? de video|minimax|wan|kling|video generation)\b/
const PROVIDED = /\b(?:solo|solamente|unicamente)\s+(?:con\s+)?(?:(?:mis|los|tus)\s+)?(?:assets|recursos|imagenes|modelos)\b|\b(?:only|just)\s+(?:(?:use|using|with)\s+)?(?:(?:my|the|our)\s+)?(?:(?:existing|provided|supplied|current|available)\s+)?(?:assets|resources|images|models)\b|\b(?:sin generar (?:nada|recursos|assets)|provided.only)\b/
const REQUEST = /\b(?:crea|creame|haz|hazme|monta|montame|comp[oó]n|componme|prepara|generame|genera|quiero|necesito|create|make|compose|prepare|build|i want)\b/
const QUESTION = /^(?:[¿?\s]*)(?:como|que|puedo|podria|can i|how|what)\b|\b(?:quiero|necesito|me gustaria)\s+(?:saber|entender|aprender)\b|\b(?:i want|i would like|i'd like)\s+to\s+(?:know|learn|understand)\b|\b(?:explicame|explain|tell me how|dime como|ensename como)\b/
const NEGATED = /\b(?:no (?:quiero|uses?|utilices?)|don't use|do not use)\s+(?:el\s+)?(?:video\s*3d|compositor|programmatic)\b/
const NEGATION = /\b(?:no|not|never|don't|dont|sin|without|nunca|jamas)\b/
const NEGATED_COMMAND = /^\s*(?:no|not|never|don't|dont|nunca|jamas)\b/
const PERMISSION = /\b(?:puedes|permite|permito|autoriza|autorizo)\s+generar\s+(?:imagenes|modelos|assets|audio|musica)\b|\b(?:allow|you may)\s+(?:generate|generating|generation of)\s+(?:images|models|assets|audio|music)\b/
const ASSET_CREATION = /\b(?:generar|generes|generate|generating|generation)\b[^.!?;\n]{0,35}\b(?:imagenes|modelos|assets|recursos|audio|musica|images|models|music)\b/

function instructionText(request: string) {
  // Dialogue, lyrics and code examples are payload, never generation authority.
  return normalize(request.replace(/```[\s\S]*?```|"[^"]*"|“[^”]*”|«[^»]*»|`[^`]*`|(?<!\w)'[^'\n]+'(?!\w)/g, ''))
}
const clauses = (value: string) => value.split(/[.!?;,\n]+/)

export function requestedProgrammaticPolicy(request: string): AgentPrepareProgrammaticVideoAction['generationPolicy'] {
  const value = instructionText(request)
  const parts = clauses(value)
  if (PROVIDED.test(value) || parts.some(part => NEGATION.test(part) && ASSET_CREATION.test(part))) return 'provided_only'
  // This grants non-video asset creation only when explicitly allowed. Merely
  // mentioning a spaceship or a song never grants a model/audio generation job.
  return parts.some(part => !NEGATION.test(part) && PERMISSION.test(part))
    ? 'no_video_generation' : 'provided_only'
}

/** Run before the legacy generic "generate a video" repair. Never execute a
 * guessed Studio/Director fallback when the user requested the compositor. */
export function reconcileProgrammaticVideoRequest(request: string, turn: AgentTurn): AgentTurn | null {
  const value = instructionText(request)
  if (!VIDEO_CONTEXT.test(value) || !(PROGRAMMATIC.test(value) || PROVIDED.test(value)) || NEGATED.test(value)) return null
  if (QUESTION.test(value) || !clauses(value).some(part => !NEGATED_COMMAND.test(part) && REQUEST.test(part))) {
    return { ...turn, reply: 'Puedes pedir: «Monta una escena con Video3D, sólo con mis assets, sin vídeo generativo». El Wizard prepara el formulario visible; desde allí revisas los recursos, montas la escena y la exportas. No se lanza ningún generador al preparar.', actions: [] }
  }
  const prepared = turn.actions.find(action => action.type === 'prepare_programmatic_video' && action.sceneCommand)
  if (prepared?.type === 'prepare_programmatic_video') {
    // Keep the exact shared command, but never a guessed Studio/Director GPU fallback.
    return {
      ...turn,
      reply: 'Preparo Video3D con tu petición literal y sin vídeo generativo. No crearé recursos nuevos salvo permiso explícito. Revisa los assets y la receta en el formulario antes de montar o exportar; todavía no hay un vídeo terminado.',
      actions: [prepared],
    }
  }
  const rhythmic = turn.actions.find(action => action.type === 'create_rhythmic_3d_video')
  const asksForSong = clauses(value).some(part => !NEGATED_COMMAND.test(part) && /\b(?:crea|genera|haz|create|generate|make)\s+(?:una?\s+|a\s+)?(?:cancion|musica|song|music)\b/.test(part))
  if (rhythmic?.type === 'create_rhythmic_3d_video' && (rhythmic.audioOutputName || (asksForSong && !PROVIDED.test(value)))) {
    // Preserve the existing compositor workflow only when its possible music
    // generation was requested, or an exact existing audio source is used.
    return { ...turn, actions: [rhythmic] }
  }
  return {
    ...turn,
    reply: 'Preparo Video3D con tu petición literal y sin vídeo generativo. No crearé recursos nuevos salvo permiso explícito. Revisa los assets y la receta en el formulario antes de montar o exportar; todavía no hay un vídeo terminado.',
    actions: [{ type: 'prepare_programmatic_video', intent: request, generationPolicy: requestedProgrammaticPolicy(request), outputNames: [] }],
  }
}

export function registerProgrammaticVideoCapability(register: typeof defineCapability) {
  register<AgentPrepareProgrammaticVideoAction>({
    name: 'prepare_programmatic_video', title: 'Prepare programmatic Video3D',
    description: 'Open the visible Video3D recipe form without running any generator, planning model, render or export. Existing assets only by default. For the built-in SFX showcase, set scene_command EXACTLY to {"version":1,"operation":"scenes.effects.showcase","input":{"dimension":"2d","sound":true}} (or dimension 3d). For the magic/anime showcase add collection="anime" (12 effects, 36 seconds). For retro consoles/VHS add collection="retro" (10 effects, 30 seconds). The server supplies all catalog timed effects by default; never add effects, duration_seconds or prompts to this input. This opens an editable scene, with no video export. scenes.effects.apply and scenes.speech.prepare require the exact existing document.',
    useWhen: 'The user asks to compose/edit video with Video3D, the compositor, without generative video, or only supplied assets. Prefer this to prepare_video/start_generation or Director. Preserve literal dialogue and lyrics. Never claim a prepared form is a rendered video.',
    parameters: ['intent', 'output_names', 'scene_command'],
    inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'prepare_programmatic_video' }, intent: { type: 'string', minLength: 1, maxLength: 12000 }, scene_command: { type: 'object', description: 'Shared scene command: version=1, operation=scenes.effects.apply (input document,cues,replace), scenes.effects.showcase (input accepts ONLY dimension="2d" or "3d",sound:boolean,collection="all" or "anime" or "retro",document; document optional to retain an existing scene), or scenes.speech.prepare (input document,slot_id,clip_id,workspace,audio_filename,text,start,end,offset,isolate_vocals optional boolean for installed-only local voice isolation). Supply the exact current document, never invent its objects or resource names.' }, output_names: { type: 'array', maxItems: 32, items: { type: 'string', maxLength: 300 } } }, required: ['type', 'intent'] },
    risk: 'edit', confirmation: 'none', progress: 'Preparando el compositor sin lanzar generación…',
    resolve(raw) {
      if (typeof raw.intent !== 'string' || !raw.intent.trim()) return null
      const names = Array.isArray(raw.output_names) ? raw.output_names : []
      if (names.length > 32 || names.some(name => typeof name !== 'string' || !name.trim() || name.length > 300)) return null
      // The LLM cannot grant generation permission through its own schema.
      return { type: 'prepare_programmatic_video', intent: raw.intent.slice(0, 12000), generationPolicy: 'provided_only', outputNames: [...new Set(names as string[])], ...(raw.scene_command && typeof raw.scene_command === 'object' ? { sceneCommand: raw.scene_command as import('../sceneFx/wizard').ScenePreparationCommand } : {}) }
    },
    validate(action) { return action.intent.trim() && ['provided_only', 'no_video_generation'].includes(action.generationPolicy) ? [] : ['intent and a restricted generation policy are required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      if (action.sceneCommand) {
        const { isScenePreparationCommand, prepareWizardScene } = await import('../sceneFx/wizard')
        if (!isScenePreparationCommand(action.sceneCommand)) throw new Error('Invalid scene command.')
        return prepareWizardScene(action.sceneCommand)
      }
      return context.adapters.video3d.prepareProgrammaticVideo(action)
    },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'prepared' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['recipe'], replay: 'atomic' },
  })
}
