import {
  cancelCanonicalQueueTask,
  inspectCanonicalQueue,
  resumeCanonicalQueueTask,
  retryCanonicalQueueTask,
} from './queueActions'
import type { InspectQueueCommand, QueueTaskCommand } from './commands'

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
