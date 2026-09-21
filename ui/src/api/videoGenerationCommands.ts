import { createGenerationCommandClient } from './generationCommandClient'
import { detachedVideoGenerationCommand } from '../lib/videoGenerationCommand'

const client = createGenerationCommandClient({
  operation: 'generation.video', label: 'Video generation',
  storagePrefix: 'hocus:inspector-video:v1', contextStoragePrefix: 'hocus:inspector-video-context:v1',
  pendingChangedEvent: 'hocus:inspector-video-pending', detach: detachedVideoGenerationCommand,
})

export function createVideoGenerationCommand(params: Record<string, unknown>, intentId: string) {
  const { workspace, ...input } = params
  return detachedVideoGenerationCommand({ version: 2, operation: 'generation.video', intent_id: intentId,
    input: { workspace, params: input } })
}

export const submitVideoGenerationCommand = client.submit
