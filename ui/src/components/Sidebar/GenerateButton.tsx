import { useState, useEffect } from 'react'
import { Play, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { splitPromptSchedule } from '../../lib/promptScheduler'

export function GenerateButton() {
  const jobs = useStore(s => s.jobs)
  const startGeneration = useStore(s => s.startGeneration)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const [cooldown, setCooldown] = useState(false)

  // Check if i2v-only model needs a start image
  const isI2vOnly = useStore(s => s.modelOptions?.i2v_class && !s.modelOptions?.t2v_class)
  const hasStartImage = useStore(s => !!(s.startImage || s.params.image_start))
  const needsImage = isI2vOnly && !hasStartImage
  const promptSchedulerEnabled = useStore(s => s.promptSchedulerEnabled)
  const generationMode = useStore(s => s.generationMode)
  const imageMode = useStore(s => s.params.image_mode)
  const prompt = useStore(s => s.params.prompt)
  const schedulerApplies = promptSchedulerEnabled && generationMode === 'video' && imageMode === 0
  const scheduledVideoCount = schedulerApplies ? splitPromptSchedule(prompt).length : 0
  const needsScheduledPrompts = schedulerApplies && scheduledVideoCount === 0

  // Brief gray flash after clicking
  useEffect(() => {
    if (!cooldown) return
    const timer = setTimeout(() => setCooldown(false), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const handleClick = () => {
    if (needsImage || needsScheduledPrompts) return
    setCooldown(true)
    startGeneration()
    setSidebarOpen(false)
  }

  const queueCount = jobs.length

  if (needsImage) {
    return (
      <button
        disabled
        className="px-4 py-2 rounded-lg flex items-center gap-1.5 bg-amber-500/20 text-amber-400 cursor-not-allowed text-xs font-medium whitespace-nowrap"
      >
        <AlertTriangle size={13} />
        Need image
      </button>
    )
  }

  return (
    <button
      onClick={handleClick}
      disabled={cooldown || needsScheduledPrompts}
      className={`px-4 py-2 rounded-lg flex items-center gap-1.5 font-medium text-xs transition-all whitespace-nowrap ${
        cooldown || needsScheduledPrompts
          ? 'bg-bg-active text-text-muted cursor-not-allowed'
          // Default theme: bg-cta resolves to a flat accent-blue (both
          // gradient stops point at --color-accent-blue). Golden Hour:
          // resolves to a red→orange sunset gradient. shadow-accent-glow
          // is empty in default and a warm bloom in Golden Hour.
          : 'bg-cta hover:brightness-110 shadow-accent-glow text-white'
      }`}
    >
      <Play size={13} fill={cooldown || needsScheduledPrompts ? 'currentColor' : 'white'} />
      {needsScheduledPrompts
        ? 'Add prompts'
        : cooldown
          ? scheduledVideoCount > 1 ? `${scheduledVideoCount} queued` : 'Queued'
          : scheduledVideoCount > 1
            ? `Queue ${scheduledVideoCount}`
            : queueCount > 0 ? `Go (${queueCount})` : 'Generate'}
    </button>
  )
}
