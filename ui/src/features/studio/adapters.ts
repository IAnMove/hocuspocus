import {
  attachStudioReferences,
  configureStudioLoras,
  prepare3d,
  prepareAudio,
  prepareImage,
  prepareVideo,
  queueSfxPack,
  startPreparedGeneration,
} from './actions'
import {
  cancelCanonicalQueueTask,
  inspectCanonicalQueue,
  resumeCanonicalQueueTask,
  retryCanonicalQueueTask,
} from './queueActions'
import type {
  AttachStudioReferencesCommand,
  ConfigureStudioLorasCommand,
  InspectQueueCommand,
  Prepare3dCommand,
  PrepareAudioCommand,
  PrepareImageCommand,
  PrepareVideoCommand,
  QueueSfxPackCommand,
  QueueTaskCommand,
} from './commands'
import type { GenerationSubmissionContext } from './generationProvenance'

export async function inspect(command: InspectQueueCommand) {
  return inspectCanonicalQueue(command.scope)
}

export async function cancel(command: QueueTaskCommand) {
  return cancelCanonicalQueueTask(command.taskId, command.confirm)
}

export async function resume(command: QueueTaskCommand) {
  return resumeCanonicalQueueTask(command.taskId, command.confirm)
}

export async function retry(command: QueueTaskCommand) {
  return retryCanonicalQueueTask(command.taskId, command.confirm)
}

export async function prepareVideoForm(command: PrepareVideoCommand) {
  return prepareVideo(command)
}

export async function prepareImageForm(command: PrepareImageCommand) {
  return prepareImage(command)
}

export async function prepareAudioForm(command: PrepareAudioCommand) {
  return prepareAudio(command)
}

export async function prepare3dForm(command: Prepare3dCommand) {
  return prepare3d(command)
}

export async function startGeneration(context?: GenerationSubmissionContext) {
  return startPreparedGeneration(context)
}

export async function attachReferences(command: AttachStudioReferencesCommand) {
  return attachStudioReferences(command)
}

export async function configureLoras(command: ConfigureStudioLorasCommand) {
  return configureStudioLoras(command)
}

export async function queueSfx(command: QueueSfxPackCommand, context?: GenerationSubmissionContext) {
  return queueSfxPack(command, context)
}
