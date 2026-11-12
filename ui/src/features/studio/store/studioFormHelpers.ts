import type { VideoSubModeStash } from './studioEditSlice'
import { isMusicModelType, sfxModelTypes } from '../../../stores/modelCatalog'
import type { AppState } from '../../../stores/useStore'

export function audioSubModeForModel(modelType: string): import('../../../types').AudioSubMode {
  if (sfxModelTypes.has(modelType)) return 'sfx'
  return isMusicModelType(modelType) ? 'music' : 'speech'
}

export const captureVideoSubModeStash = (s: AppState): VideoSubModeStash => ({
  params: { ...s.params },
  startImage: s.startImage,
  endImage: s.endImage,
  continueVideo: s.continueVideo,
  continueVideoPath: s.continueVideoPath,
  continueVideoUrl: s.continueVideoUrl,
  continueVideoDuration: s.continueVideoDuration,
  audioGuideFilename: s.audioGuideFilename,
  imageRefs: s.imageRefs,
  imageRefType: s.imageRefType,
  removeBackgroundRefs: s.removeBackgroundRefs,
  durationSeconds: s.durationSeconds,
  slidingWindowSeconds: s.slidingWindowSeconds,
  slidingWindowOverlap: s.slidingWindowOverlap,
  clips: s.clips,
  singlePromptMode: s.singlePromptMode,
  studioFocusedClipIndex: s.studioFocusedClipIndex,
})
