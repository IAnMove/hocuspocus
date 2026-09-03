import { Mic, Music, Zap, Layers } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { AudioSubMode } from '../../types'

const modes: { value: AudioSubMode; icon: typeof Mic }[] = [
  { value: 'speech', icon: Mic },
  { value: 'music', icon: Music },
  { value: 'sfx', icon: Zap },
  { value: 'mixer', icon: Layers },
]

export function AudioSubModeToggle() {
  const { t } = useUiTranslation('studio')
  const audioSubMode = useStore(s => s.audioSubMode)
  const setAudioSubMode = useStore(s => s.setAudioSubMode)

  return (
    <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
      {modes.map(m => {
        const Icon = m.icon
        const active = audioSubMode === m.value
        return (
          <button
            key={m.value}
            onClick={() => setAudioSubMode(m.value)}
            className={`flex-1 flex items-center justify-center gap-1.5 text-xs py-1.5 rounded-md transition-all ${
              active
                ? 'bg-bg-active text-text-primary'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            <Icon size={13} />
            <span>{t(`audioSubModes.${m.value}`)}</span>
          </button>
        )
      })}
    </div>
  )
}
