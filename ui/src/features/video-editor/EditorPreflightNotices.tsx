import { useUiTranslation } from '../../i18n'
import type { EditorSoundtrack } from './editorDraft'
import type { EditorClip } from './editorClipNormalization'
import { editorPreflight, type PreflightCode } from './editorPreflight'

const KEY: Record<PreflightCode, 'preflight.timeline_gap' | 'preflight.mixed_fps' | 'preflight.mixed_resolution' | 'preflight.mix_hot'> = {
  timeline_gap: 'preflight.timeline_gap',
  mixed_fps: 'preflight.mixed_fps',
  mixed_resolution: 'preflight.mixed_resolution',
  mix_hot: 'preflight.mix_hot',
}

/** Editor warnings for gaps, mixed sources and a hot mix. Export stays available. */
export function EditorPreflightNotices({ clips, soundtrack }: {
  clips: readonly EditorClip[]
  soundtrack: EditorSoundtrack | null
}) {
  const { t } = useUiTranslation('videoEditor')
  const notices = editorPreflight({
    clips: clips.map(clip => ({
      id: clip.id, fps: clip.fps, width: clip.width, height: clip.height,
      volume: clip.volume, muted: clip.muted, hasAudio: clip.has_audio,
      trimStart: clip.trimStart, trimEnd: clip.trimEnd,
      transition: clip.transition, transitionDuration: clip.transitionDuration,
    })),
    soundtrack,
  })
  if (!notices.length) return null
  return <div className="space-y-1" data-testid="editor-preflight">
    <p className="text-[10px] text-text-muted">{t('preflight.hint')}</p>
    {notices.map(notice => <p key={`${notice.code}:${notice.t}`} className="text-[10px] text-amber-300">{t(KEY[notice.code], { time: notice.t.toFixed(2) })}</p>)}
  </div>
}
