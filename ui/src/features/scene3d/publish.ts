import { canonicalSceneFps } from '../../lib/sceneFps.ts'
import { sceneVoiceTracks } from './speech/timeline'
import { scene3dOutputDuration } from './clock.ts'
import { saveSceneRecording } from '../../api/video3d.ts'
import type { Scene3DDocument } from './types.ts'
import { world3dExportSize } from './exportMp4.ts'

export function world3dRecordingStub(document: Scene3DDocument) {
  const size = world3dExportSize(document.width, document.height)
  return {
    version: 1 as const,
    name: `${document.clipNumber ? `clip-${String(document.clipNumber).padStart(2, '0')}-` : ''}world3d-${document.templateId || 'scene'}`,
    width: size.width,
    height: size.height,
    fps: canonicalSceneFps(document.fps),
    duration: scene3dOutputDuration(document),
    layers: [] as unknown[],
  }
}

export async function publishWorld3DRecording(
  blob: Blob,
  document: Scene3DDocument,
  workspace?: string,
  audio?: Blob,
) {
  return saveSceneRecording(blob, {
    scene: world3dRecordingStub(document) as import('../../types').Scene,
    embeddedAudio: !audio && Boolean(sceneVoiceTracks(document).length || document.sfx?.some(cue => cue.sound && cue.volume) || document.worldSfx?.some(cue => cue.sound && cue.volume)),
    prompt: '',
    recipe: {
      engine: 'world3d',
      document,
      templateId: document.templateId,
      slots: document.slots.map(slot => ({
        id: slot.id,
        slot: slot.slot,
        media: slot.media,
        clip: slot.clip,
        loop: slot.loop ?? null,
      })),
    },
    workspace,
  }, audio)
}
