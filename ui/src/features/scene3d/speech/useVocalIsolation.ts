import { useState } from 'react'
import type { Scene3DSlot } from '../types'
import type { Scene3DSpeech } from './types'

export function useVocalIsolation(slot: Scene3DSlot, workspace: string, speech: Scene3DSpeech) {
  const [choice, setChoice] = useState<{ key: string; enabled: boolean }>()
  const key = JSON.stringify([workspace, slot.id, slot.sourceUrl, speech.audio?.url, speech.driver])
  const enabled = choice?.key === key ? choice.enabled : speech.driver === 'rhubarb-vocals' || speech.driver === 'phoneme-vocals'
  return [enabled, (value: boolean) => setChoice({ key, enabled: value })] as const
}
