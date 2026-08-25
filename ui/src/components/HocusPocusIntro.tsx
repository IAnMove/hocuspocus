import { useEffect, useRef, useState } from 'react'
import { SkipForward } from 'lucide-react'

export const INTRO_DURATION_MS = 4500
const INTRO_FADE_MS = 360

interface HocusPocusIntroProps {
  onComplete: () => void
}

/** A short boot identity before the existing first-run / release notes dialog. */
export function HocusPocusIntro({ onComplete }: HocusPocusIntroProps) {
  const [leaving, setLeaving] = useState(false)
  const onCompleteRef = useRef(onComplete)
  const finishedRef = useRef(false)
  onCompleteRef.current = onComplete

  const finish = () => {
    if (finishedRef.current) return
    finishedRef.current = true
    setLeaving(true)
    window.setTimeout(() => onCompleteRef.current(), INTRO_FADE_MS)
  }

  useEffect(() => {
    const fadeTimer = window.setTimeout(() => setLeaving(true), INTRO_DURATION_MS)
    const doneTimer = window.setTimeout(() => {
      if (finishedRef.current) return
      finishedRef.current = true
      onCompleteRef.current()
    }, INTRO_DURATION_MS + INTRO_FADE_MS)
    return () => {
      window.clearTimeout(fadeTimer)
      window.clearTimeout(doneTimer)
    }
  }, [])

  return (
    <section
      aria-label="HocusPocus is starting"
      className={`fixed inset-0 z-[200] isolate flex items-center justify-center overflow-hidden bg-[#09070d] px-6 transition-opacity duration-300 ${leaving ? 'opacity-0' : 'opacity-100'}`}
    >
      <img
        src="/hocuspocus/scribe-keyart.png"
        alt=""
        className="absolute inset-0 h-full w-full scale-105 object-cover object-center opacity-55 blur-[1px]"
      />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_48%,rgba(111,79,190,0.26),transparent_31%),linear-gradient(90deg,rgba(6,5,10,0.94),rgba(7,5,11,0.25),rgba(6,5,10,0.94))]" />
      <div className="relative flex max-w-lg flex-col items-center text-center">
        <img src="/hocuspocus-icon.png" alt="" className="h-20 w-20 object-contain drop-shadow-[0_0_28px_rgba(53,109,255,0.55)]" />
        <p className="mt-6 text-[10px] font-semibold uppercase tracking-[0.46em] text-violet-200/80">Forge stories. Shape worlds.</p>
        <h1 className="mt-2 font-serif text-5xl font-semibold tracking-tight text-white drop-shadow-lg sm:text-6xl">HocusPocus</h1>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-violet-100/75">The local studio to imagine, direct, and turn worlds into images, video, sound, and 3D.</p>
      </div>
      <button
        type="button"
        onClick={finish}
        className="absolute bottom-6 right-6 flex items-center gap-1.5 rounded-full border border-white/15 bg-black/20 px-3 py-1.5 text-[11px] text-white/70 backdrop-blur transition hover:border-violet-300/60 hover:text-white"
      >
        <SkipForward size={13} /> Skip
      </button>
    </section>
  )
}
