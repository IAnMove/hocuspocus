import type { RefObject } from 'react'
import { Music } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { panel, type StoryMusicQueue } from './storyLabChrome'
import type { StoryGenerationScope, StoryMusicCue, StoryProject } from './types'
import { MusicCueCard } from './MusicCueCard'
import { ManualSongPanel } from './ManualSongPanel'
import { StoryMusicHeader } from './StoryMusicHeader'
import { StoryMusicSettingsBar } from './StoryMusicSettingsBar'

export type StoryMusicTabProps = {
  project: StoryProject
  patch: (value: Partial<StoryProject>) => void
  instruction: string
  setInstruction: (value: string) => void
  busy: StoryGenerationScope | null
  productionBusy: 'film' | 'music' | 'trailer' | null
  musicQueue: StoryMusicQueue | null
  musicCueBusy: string
  newSongAction: 'prompts' | 'audio' | null
  musicWritingReady: boolean
  minimaxConfigured: boolean
  storyVideoConfigurationReady: boolean
  workspace: string
  musicVersionStyle: Record<string, string>
  setMusicVersionStyle: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  musicVersionLanguage: Record<string, string>
  setMusicVersionLanguage: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  lyricsTranslationLanguage: Record<string, string>
  setLyricsTranslationLanguage: (value: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => void
  generate: (scope: StoryGenerationScope) => void
  generateAllMusicCues: () => void
  cancelMusicQueue: () => void
  createNewMusicVideoSong: (withAudio: boolean) => void
  createAllMusicCueVersions: () => void
  patchMusicCue: (cueId: string, changes: Partial<StoryMusicCue>) => void
  adaptMusicCueWithLlm: (cueId: string, includeLyria?: boolean) => void
  createMusicCueVersion: (cueId: string) => void
  translateMusicCueLyrics: (cueId: string) => void
  generateMusicCueAudio: (cueId: string) => void
  openMusicalTrailer: (candidateId?: string) => void
  onImportCustomMp3: (cueId: string) => void
  onImportLyria: (cueId: string) => void
  onCopied: (text: string) => void
  musicCoverRef: RefObject<HTMLInputElement | null>
  uploadCoverReference: (file?: File) => void
  writeStorySong: () => void
  adaptStoryLyrics: () => void
  translateManualSongLyrics: () => void
  createManualSongVersion: () => void
  generateMinimaxSongs: () => void
}

export function StoryMusicTab(props: StoryMusicTabProps) {
  const { t } = useUiTranslation('storyLab')
  const { project } = props

  return (
    <>
      <StoryMusicHeader {...props} />
      <StoryMusicSettingsBar {...props} />

      {(['world', 'character', 'story'] as const).map(kind => {
        const cues = project.music.cues.filter(cue => cue.kind === kind)
        if (!cues.length) return null
        const heading = kind === 'world' ? t('music.worldAmbience')
          : kind === 'character' ? t('music.characterThemes') : t('music.storySongs')
        return (
          <section key={kind} className="mb-5">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">{heading}</h3>
            <div className="space-y-3">
              {cues.map(cue => <MusicCueCard key={cue.id} cue={cue} kind={kind} {...props} />)}
            </div>
          </section>
        )
      })}

      {!project.music.cues.length && (
        <div className={`${panel} mb-5 py-12 text-center`}>
          <Music size={30} className="mx-auto mb-3 text-pink-400" />
          <p className="text-sm text-text-primary">{t('music.emptyTitle')}</p>
          <p className="mt-1 text-xs text-text-muted">{t('music.emptyHint')}</p>
        </div>
      )}

      <ManualSongPanel {...props} />
    </>
  )
}
