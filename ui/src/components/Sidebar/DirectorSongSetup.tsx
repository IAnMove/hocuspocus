import { Music } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

// Director Music Video — "Generate a track" up-front options. The description
// itself is typed into the bottom chat (its Send button kicks off the whole
// write-song → render → analyze → video chain), so this panel only holds the
// small choices: instrumental + length. The LLM writes the Style + Lyrics
// internally — power users who want to hand-edit those use Studio → Audio → Music.
export function DirectorSongSetup() {
  const { t } = useUiTranslation('director')
  const instrumental = useStore(s => s.directorSongInstrumental)
  const setInstrumental = useStore(s => s.setDirectorSongInstrumental)
  const duration = useStore(s => s.directorSongDuration)
  const setDuration = useStore(s => s.setDirectorSongDuration)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-[11px] text-text-muted uppercase tracking-wider flex items-center gap-1.5">
          <Music size={12} /> {t('song.title')}
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer text-[10px] text-text-secondary hover:text-text-primary transition-colors">
          <input
            type="checkbox"
            checked={instrumental}
            onChange={e => setInstrumental(e.target.checked)}
            className="accent-accent-blue"
          />
          {t('song.instrumental')}
        </label>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('song.length')}</label>
          <span className="text-[10px] text-text-secondary tabular-nums">{t('song.duration', { count: duration })}</span>
        </div>
        <input
          type="range"
          min={30}
          max={300}
          step={10}
          value={duration}
          onChange={e => setDuration(Number(e.target.value))}
          className="w-full accent-accent-blue"
        />
      </div>

      <p className="text-[10px] text-text-muted leading-snug">
        {instrumental ? t('song.hintInstrumental') : t('song.hint')}
      </p>
    </div>
  )
}
