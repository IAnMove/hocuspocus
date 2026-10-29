import i18n from '../../i18n'
import { controlLabel } from '../../i18n/controlLabel'
import type { DirectorShotImageGuidance } from '../../types'

export function directorSendLabel(chatInputEnabled: boolean, loading: boolean, mvGenerateSetup: boolean, songDescription: string, resolvedChatInput: string) {
  if (!chatInputEnabled) return controlLabel(loading ? 'disabled.sendWhileBusy' : 'disabled.sendNeedsStep')
  const text = mvGenerateSetup ? songDescription : resolvedChatInput
  if (!text.trim()) return controlLabel('disabled.sendNeedsText')
  return controlLabel('a11y.send')
}

export function directorWillGenerateShotImages(
  support: 'required' | 'optional' | 'direct_references' | undefined,
  guidance: DirectorShotImageGuidance,
  hasVisualReferences: boolean,
): boolean {
  if (!support || support === 'required') return true
  if (guidance === 'generate') return true
  if (support === 'direct_references' || guidance === 'prompt_only') return false
  return hasVisualReferences
}

export function directorText(key: string, options?: Record<string, unknown>) {
  return String(i18n.t(key, key, { ns: 'director', ...options }))
}

const SECTION_LABEL_KEYS: Record<string, string> = {
  intro: 'chat.section.intro',
  verse: 'chat.section.verse',
  'pre-chorus': 'chat.section.preChorus',
  chorus: 'chat.section.chorus',
  bridge: 'chat.section.bridge',
  outro: 'chat.section.outro',
  instrumental: 'chat.section.instrumental',
  dialogue: 'chat.section.dialogue',
  action: 'chat.section.action',
  opening: 'chat.section.opening',
  closing: 'chat.section.closing',
  scene: 'chat.section.scene',
}

export function sectionDisplayName(label: string) {
  const key = SECTION_LABEL_KEYS[label]
  return key ? directorText(key) : label
}

const IMAGE_PROGRESS_KEYS: Record<string, string> = {
  generating: 'chat.progress.generating',
  polling: 'chat.progress.polling',
  downloading: 'chat.progress.downloading',
  processing: 'chat.progress.processing',
}

function imageProgressStatus(status: string) {
  const key = IMAGE_PROGRESS_KEYS[status]
  return key ? directorText(key) : status
}

export function imageSpinnerLabel(status: string | undefined) {
  if (status === 'generating') return directorText('panel.imageStatus.generating')
  if (status === 'polling') return directorText('panel.imageStatus.polling')
  if (status === 'downloading') return directorText('panel.imageStatus.downloading')
  return directorText('panel.imageStatus.processing')
}

export function imageGenStatusLine(label: string, status: string) {
  if (status === 'done') return label
  return directorText('chat.clipStatus', { label, status: imageProgressStatus(status) })
}

export function directorChatPlaceholder(state: {
  skill: string | null | undefined
  mvGenerateSetup: boolean
  isShortFilm: boolean
  shortFilmPath: string | null | undefined
  step: string
  isMvGenerate: boolean
  isStoryPath: boolean
  speakerCount: number
}) {
  if (!state.skill) return directorText('chat.chooseSkill')
  if (state.mvGenerateSetup) return directorText('chat.mvPromptPlaceholder')
  if (state.isShortFilm && !state.shortFilmPath) return directorText('chat.choosePath')
  if (state.step === 'upload' || state.step === 'analyze') {
    if (state.isMvGenerate) return directorText('chat.generatingMusicVideo')
    return directorText(state.isShortFilm ? 'chat.uploadDialogueToBegin' : 'chat.uploadAudioToBegin')
  }
  if (state.step === 'style') {
    if (state.isStoryPath) return directorText('chat.storyExamplePlaceholder')
    if (state.isShortFilm) return directorText('chat.shortFilmMoodPlaceholder')
    return directorText(state.speakerCount >= 2 ? 'panel.scenePlaceholderMulti' : 'chat.sceneAndCharactersPlaceholder')
  }
  if (state.step === 'structure') return directorText(state.isShortFilm ? 'chat.adjustScenePacing' : 'chat.adjustClipStructure')
  return directorText('chat.reviewing')
}

export function planPhaseLabel(phase: string | undefined, isStoryPath: boolean, isShortFilm: boolean, usesShotImages: boolean) {
  if (phase === 'polishing_prompts') return directorText('chat.polishingPrompts')
  if (isStoryPath) return directorText(usesShotImages ? 'chat.planningScenesAndPrompts' : 'chat.planningScenesAndVideo')
  if (isShortFilm) return directorText(usesShotImages ? 'chat.writingScenePrompts' : 'panel.writingVideoPrompts')
  return directorText(usesShotImages ? 'chat.writingImageAndVideo' : 'panel.writingVideoPrompts')
}

export function shotGuidanceHint(
  support: 'required' | 'optional' | 'direct_references' | undefined,
  guidance: DirectorShotImageGuidance,
  hasVisualReferences: boolean,
  generateShotImages: boolean,
) {
  if (support === 'direct_references') {
    if (guidance === 'generate') return directorText('chat.guidanceCompose')
    if (!hasVisualReferences) return directorText('chat.guidanceNeedImage')
    return directorText('chat.guidanceDirectRefs')
  }
  if (generateShotImages) return directorText('chat.guidanceStartFrames')
  return directorText('chat.guidanceFromPrompt')
}

export function videoStepsHint(
  turboSelected: boolean,
  turboSteps: number | undefined,
  locked: boolean,
  videoSteps: number | null,
  defaultSteps: number | null,
) {
  if (turboSelected) return directorText('chat.turboRecipe', { steps: turboSteps ?? 6 })
  if (locked) return directorText('chat.stepsFixed')
  if (videoSteps == null) return directorText('chat.stepsLoading')
  if (defaultSteps === videoSteps) return directorText('chat.stepsForModelDefault')
  return directorText('chat.stepsForModel')
}

export function maxShotHint(manual: number | null, safe: number | null, time: string, resolution: string, gb: string) {
  if (manual == null) {
    if (safe != null) return directorText('chat.autoPlansAtMost', { time, resolution, gb })
    return directorText('chat.autoDerivesLimit')
  }
  if (safe != null && manual > safe) return directorText('chat.manualOverrideVram', { time })
  return directorText('chat.manualShotLimit')
}
