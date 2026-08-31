import { fetchOutputs } from '../../api/client'
import { useStore } from '../../stores/useStore'
import type { AgentCreateRhythmic3dVideoAction, AgentPrepareAudioAction } from './agentActions'
import type { WizardApplicationAdapters } from './applicationAdapters'
import {
  defaultWizardWorkflowRuntime,
  type WizardWorkflowDefinition,
  type WizardWorkflowRecord,
  type WizardWorkflowStepContext,
  type WizardWorkflowStepResult,
} from './wizardWorkflowRuntime'

export const RHYTHMIC_3D_WORKFLOW = 'create_rhythmic_3d_video'
let registered = false

function input(context: WizardWorkflowStepContext): AgentCreateRhythmic3dVideoAction {
  return context.inputSnapshot as unknown as AgentCreateRhythmic3dVideoAction
}

function basename(value: string): string {
  return decodeURIComponent(value.split(/[\\/]/).at(-1) || value)
}

export async function resolveRhythmic3dAudioName(context: WizardWorkflowStepContext): Promise<string> {
  const action = input(context)
  const candidates = action.audioOutputName
    ? [action.audioOutputName]
    : context.workflow.outputRefs.map(basename)
  const library = await fetchOutputs(0, 0, { mediaType: 'audio', workspace: context.workflow.workspace })
  const matches = library.outputs.filter(output => candidates.some(candidate => candidate === output.name || basename(candidate) === output.name))
  if (matches.length !== 1) {
    throw new Rhythmic3dAudioSelectionRequired(
      matches.length
        ? 'La tarea publicó varios audios. Elige cuál debe mover la escena.'
        : 'No pude correlacionar un único audio. Elige un audio real de este workspace para continuar.',
      (matches.length ? matches : library.outputs).slice(0, 30).map(output => output.name),
    )
  }
  return matches[0].name
}

class Rhythmic3dAudioSelectionRequired extends Error {
  readonly names: string[]

  constructor(message: string, names: string[]) {
    super(message)
    this.name = 'Rhythmic3dAudioSelectionRequired'
    this.names = names
  }
}

async function resolveAudioForStep(
  context: WizardWorkflowStepContext,
  resolver: (context: WizardWorkflowStepContext) => Promise<string>,
): Promise<string | WizardWorkflowStepResult> {
  try {
    return await resolver(context)
  } catch (error) {
    if (!(error instanceof Rhythmic3dAudioSelectionRequired)) throw error
    return {
      state: 'awaiting_input',
      awaitingInput: {
        reason: error.message,
        fields: ['audioOutputName'],
        options: error.names.map(name => ({ value: name, label: name, field: 'audioOutputName' })),
        recommended: error.names[0] || null,
      },
    }
  }
}

export function createRhythmic3dWorkflowDefinition(
  applicationAdapters: WizardApplicationAdapters,
  resolveAudioName: (context: WizardWorkflowStepContext) => Promise<string> = resolveRhythmic3dAudioName,
): WizardWorkflowDefinition {
  return {
    type: RHYTHMIC_3D_WORKFLOW,
    steps: [
      {
        stepId: 'resolve-song', kind: 'prepare/generate song',
        async execute(context) {
          const action = input(context)
          if (action.audioOutputName) {
            const name = await resolveAudioForStep(context, resolveAudioName)
            if (typeof name !== 'string') return name
            return { state: 'completed', output: { audioOutputName: name }, outputRefs: [name] }
          }
          const song: AgentPrepareAudioAction = {
            type: 'prepare_audio', subMode: 'music', prompt: action.musicPrompt,
            durationSeconds: action.durationSeconds,
          }
          const outcome = await applicationAdapters.studio.queueMusic(song)
          if (!outcome.taskId) throw new Error('La canción no devolvió un taskId canónico.')
          return { state: 'queued', taskId: outcome.taskId, output: { prompt: action.musicPrompt } }
        },
      },
      {
        stepId: 'create-scene', kind: 'create editable 3D scene',
        async execute(context) {
          const action = input(context)
          const outcome = await applicationAdapters.video3d.run({ type: 'create_3d_scene', sceneName: action.sceneName, durationSeconds: action.durationSeconds, width: 1280, height: 720, fps: 30, reset: true })
          return { state: 'completed', output: { message: outcome.message }, resolvedEntityIds: { sceneId: action.sceneName } }
        },
      },
      {
        stepId: 'build-layers', kind: 'add visual layers and camera',
        async execute(context) {
          const action = input(context)
          await applicationAdapters.video3d.run({ type: 'create_3d_scene', sceneName: action.sceneName, durationSeconds: action.durationSeconds, width: 1280, height: 720, fps: 30 })
          const visualType = /\.glb$/i.test(action.visualOutputName) ? 'model3d'
            : /\.(mp4|webm|mov)$/i.test(action.visualOutputName) ? 'video' : 'image'
          const visual = await applicationAdapters.video3d.run({ type: 'add_3d_scene_layer', sceneName: action.sceneName, layerName: action.layerName, layerType: visualType, outputName: action.visualOutputName })
          const camera = await applicationAdapters.video3d.run({ type: 'add_3d_scene_layer', sceneName: action.sceneName, layerName: 'Rhythm camera', layerType: 'camera' })
          return { state: 'completed', output: { visual: visual.message, camera: camera.message }, resolvedEntityIds: { visualLayerId: visual.layerIds?.[0] || '', cameraLayerId: camera.layerIds?.[0] || '' } }
        },
      },
      {
        stepId: 'attach-audio', kind: 'resolve and attach exact audio',
        async execute(context) {
          const action = input(context); const audioOutputName = await resolveAudioForStep(context, resolveAudioName)
          if (typeof audioOutputName !== 'string') return audioOutputName
          const outcome = await applicationAdapters.video3d.run({ type: 'attach_3d_scene_audio', sceneName: action.sceneName, audioOutputName })
          return { state: 'completed', output: { audioOutputName, message: outcome.message }, outputRefs: [audioOutputName], resolvedEntityIds: { audioTrackId: outcome.audioTrackId || '' } }
        },
      },
      {
        stepId: 'analyze-audio', kind: 'analyze audio once',
        async execute(context) {
          const action = input(context); const audioOutputName = await resolveAudioForStep(context, resolveAudioName)
          if (typeof audioOutputName !== 'string') return audioOutputName
          const outcome = await applicationAdapters.video3d.run({ type: 'analyze_3d_scene_audio', sceneName: action.sceneName, audioOutputName })
          return { state: 'completed', output: { audioOutputName, bpm: outcome.bpm, beatCount: outcome.beatCount, downbeatCount: outcome.downbeatCount, rhythmGrid: outcome.rhythmGrid }, resolvedEntityIds: { analysisId: outcome.analysisId || '' } }
        },
      },
      {
        stepId: 'bake-choreography', kind: 'bake editable beat choreography',
        async execute(context) {
          const action = input(context); const audioOutputName = await resolveAudioForStep(context, resolveAudioName)
          if (typeof audioOutputName !== 'string') return audioOutputName
          const analysisStep = context.workflow.steps.find(step => step.stepId === 'analyze-audio')
          const rhythmGrid = analysisStep?.output.rhythmGrid as import('./agentUiBus').AgentRhythmGrid | undefined
          if (!rhythmGrid?.beats.length) throw new Error('El checkpoint no contiene la rejilla rítmica analizada.')
          const subject = await applicationAdapters.video3d.run({ type: 'apply_3d_choreography', sceneName: action.sceneName, layerName: action.layerName, audioOutputName, cueSource: action.cueSource, profile: action.profile, intensity: action.intensity, rhythmGrid })
          const camera = await applicationAdapters.video3d.run({ type: 'apply_3d_choreography', sceneName: action.sceneName, layerName: 'Rhythm camera', audioOutputName, cueSource: 'downbeats', profile: 'camera-punch', intensity: Math.min(.45, action.intensity), rhythmGrid })
          return { state: 'completed', output: { subject: subject.message, camera: camera.message } }
        },
      },
      {
        stepId: 'save-scene', kind: 'save editable scene',
        async execute(context) {
          const action = input(context)
          const outcome = await applicationAdapters.video3d.run({ type: 'save_3d_scene', sceneName: action.sceneName })
          return { state: 'completed', output: { message: outcome.message }, outputRefs: outcome.outputNames }
        },
      },
      {
        stepId: 'export-video', kind: 'export and publish MP4',
        async execute(context) {
          const action = input(context)
          const outcome = await applicationAdapters.video3d.run({ type: 'export_3d_scene', sceneName: action.sceneName })
          return { state: 'completed', output: { message: outcome.message }, outputRefs: outcome.outputNames }
        },
      },
    ],
  }
}

export function ensureRhythmic3dWorkflowRegistered(applicationAdapters: WizardApplicationAdapters): void {
  if (registered) return
  defaultWizardWorkflowRuntime.register(createRhythmic3dWorkflowDefinition(applicationAdapters))
  registered = true
}

export async function startRhythmic3dWorkflow(
  action: AgentCreateRhythmic3dVideoAction,
  applicationAdapters: WizardApplicationAdapters,
): Promise<WizardWorkflowRecord> {
  ensureRhythmic3dWorkflowRegistered(applicationAdapters)
  const workspace = useStore.getState().activeWorkspace || 'default'
  return defaultWizardWorkflowRuntime.start({
    type: RHYTHMIC_3D_WORKFLOW,
    workspace,
    userRequest: action.musicPrompt || `Use ${action.audioOutputName}`,
    inputSnapshot: { ...action },
    confirmationScope: ['generate_song', 'save_scene', 'export_video'],
  })
}
