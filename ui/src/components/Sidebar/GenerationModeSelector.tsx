import { Image, Video, AudioLines, Wand2, Wrench, Box, Settings } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import type { GenerationMode } from '../../types'

const modes: { value: GenerationMode; label: string; icon: typeof Image }[] = [
  { value: 'image', label: 'Image', icon: Image },
  { value: 'video', label: 'Video', icon: Video },
  { value: 'audio', label: 'Audio', icon: AudioLines },
  { value: 'model3d', label: '3D', icon: Box },
  { value: 'avatar', label: 'Edit', icon: Wand2 },
  { value: 'tools', label: 'Tools', icon: Wrench },
]

export function GenerationModeSelector() {
  const generationMode = useStore(s => s.generationMode)
  const setGenerationMode = useStore(s => s.setGenerationMode)
  const setSettingsOpen = useStore(s => s.setSettingsOpen)

  return (
    <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border" data-wizard-anchor="mode">
      {modes.map(m => {
        const Icon = m.icon
        const active = generationMode === m.value
        return (
          <button
            key={m.value}
            onClick={() => setGenerationMode(m.value)}
            className={`flex-1 flex items-center justify-center gap-1.5 text-xs py-2 rounded-md transition-all ${
              active
                ? 'bg-bg-active text-text-primary'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            <Icon size={14} />
            <span>{m.label}</span>
          </button>
        )
      })}
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        className="flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-xs text-text-secondary transition-all hover:text-text-primary"
        title="Settings"
      >
        <Settings size={14} />
        <span>Settings</span>
      </button>
    </div>
  )
}
