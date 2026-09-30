import { useEffect, useMemo, useState } from 'react'
import { Smile } from 'lucide-react'
import type { CharacterKit } from '../../lib/characterKit'
import { MOUTH_SOUND_GROUPS, mouthStateForSound } from '../../lib/characterMouthStates'

/** Only the hovered/focused card swaps images. No video, canvas or model work. */
export function LipsThumbnail({ pack, animate = false }: { pack: CharacterKit; animate?: boolean }) {
  const sources = useMemo(() => [...new Set(MOUTH_SOUND_GROUPS.map(sound => {
    const state = mouthStateForSound(sound, pack.mouthMapping)
    return pack.mouth[state]?.source || pack.mouthCandidates?.[state]?.source
  }).filter((source): source is string => Boolean(source)))], [pack.mouth, pack.mouthMapping, pack.mouthCandidates])
  const [frame, setFrame] = useState(0)
  useEffect(() => {
    if (!animate || sources.length < 2 || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const timer = window.setInterval(() => setFrame(value => value + 1), 180)
    return () => window.clearInterval(timer)
  }, [animate, sources.length])
  const source = sources[animate ? frame % sources.length : 0]
  return <div className="flex aspect-[4/3] items-center justify-center rounded-xl bg-bg-primary p-6">
    {source ? <img src={source} alt="" loading="lazy" className="max-h-24 max-w-full object-contain" /> : <Smile className="text-text-muted" size={40} strokeWidth={1.2} />}
  </div>
}
