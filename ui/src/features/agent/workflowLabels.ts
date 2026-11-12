import i18n from '../../i18n'

const STEP_KEYS: Record<string, string> = {
  'prepare/generate song': 'workflowSteps.prepareSong',
  'create editable 3D scene': 'workflowSteps.createScene',
  'add visual layers and camera': 'workflowSteps.addLayers',
  'resolve and attach exact audio': 'workflowSteps.attachAudio',
  'analyze audio once': 'workflowSteps.analyzeAudio',
  'bake editable beat choreography': 'workflowSteps.bakeChoreography',
  'save editable scene': 'workflowSteps.saveScene',
  'export and publish MP4': 'workflowSteps.exportMp4',
  'generation.image': 'workflowSteps.generateImage',
  'tools.upscale': 'workflowSteps.upscale',
}

function catalogLabel(key: string, raw: string) {
  return String(i18n.t(key, raw, { ns: 'wizard' }))
}

/** A known workflow type, or the server id when this build has no name for it. */
export function workflowTypeLabel(type: string) {
  return catalogLabel(`workflowTypes.${type}`, type)
}

/** A known workflow state, or the raw state code. */
export function workflowStateLabel(state: string) {
  return catalogLabel(`executionState.${state}`, state)
}

/** A known job state, or the server's own word. */
export function jobStatusLabel(status: string) {
  return String(i18n.t(`status.${status}`, status, { ns: 'common' }))
}

/** A known step kind, or the raw kind string. */
export function workflowStepLabel(kind: string) {
  const key = STEP_KEYS[kind]
  return key ? catalogLabel(key, kind) : kind
}
