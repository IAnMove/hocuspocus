import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { SkipForward } from 'lucide-react'
import { useUiTranslation } from '../i18n'

/** How long the poster holds — measured from the moment the key art is
 *  actually on screen, not from mount. See the readiness gate below. */
export const INTRO_DURATION_MS = 4500
/** Shorter hold when the OS asks for reduced motion: with the
 *  choreography switched off there is nothing left to watch, so the
 *  plate is only an identity card. */
export const INTRO_REDUCED_DURATION_MS = 2600
/** The dissolve into the app. Also drives the CSS transition, via the
 *  --hp-intro-fade custom property, so the two cannot drift apart. */
export const INTRO_FADE_MS = 520
/** Cap on waiting for the art to decode. A splash that stalls on a cold
 *  cache is worse than one that starts a beat early. */
export const INTRO_ASSET_TIMEOUT_MS = 1500
/** Physical pixels above which the plate drops its two full-screen,
 *  per-pixel effects (the exit blur and the soft-light grain). Both cost
 *  in proportion to the window, so a 4K panel (~8.3M px) pays around
 *  four times what a 1080p one does for the same dissolve — which is
 *  where the stutter came from. A 16" laptop at 2x (~7.7M) still gets
 *  the full plate. */
export const INTRO_RICH_PIXEL_BUDGET = 8_000_000

/** How much of the choreography this window can afford. Everything else
 *  in the intro is transform/opacity only, so it survives a busy main
 *  thread; these two effects are the ones that scale with resolution. */
function introQualityTier(): 'rich' | 'lite' {
  const dpr = window.devicePixelRatio || 1
  return window.innerWidth * window.innerHeight * dpr * dpr > INTRO_RICH_PIXEL_BUDGET
    ? 'lite'
    : 'rich'
}

/** The wordmark tracks in glyph by glyph. Animating `letter-spacing`
 *  reflowed the copy column on every frame, and the intro plays while
 *  the whole studio mounts behind it — exactly the frames the main
 *  thread cannot spare. Each glyph carries its own starting offset
 *  instead, so the same beat runs entirely on the compositor. */
const WORDMARK = 'HocusPocus'
/** Matches the tracking the old `letter-spacing` keyframe started from. */
const WORDMARK_TRACKING_EM = 0.26
const WORDMARK_STAGGER_MS = 26
const WORDMARK_DELAY_MS = 900

/** Embers drifting off the quill, positioned as a fraction of the art
 *  box so they stay with the light at any window size. Scattered by
 *  hand — an even spread reads as a progress indicator, not as air. */
const MOTES = [
  { left: '71%', top: '47%', duration: '9.5s', delay: '0s', drift: '16px' },
  { left: '78%', top: '43%', duration: '11s', delay: '1.4s', drift: '-11px' },
  { left: '74%', top: '39%', duration: '8.5s', delay: '3.1s', drift: '9px' },
  { left: '82%', top: '45%', duration: '12.5s', delay: '0.7s', drift: '21px' },
  { left: '68%', top: '42%', duration: '10.5s', delay: '4.6s', drift: '-17px' },
  { left: '80%', top: '38%', duration: '9s', delay: '2.3s', drift: '13px' },
  { left: '76%', top: '49%', duration: '13s', delay: '5.8s', drift: '-8px' },
  { left: '85%', top: '41%', duration: '11.5s', delay: '3.9s', drift: '18px' },
  { left: '70%', top: '36%', duration: '10s', delay: '6.9s', drift: '-14px' },
]

interface HocusPocusIntroProps {
  onComplete: () => void
  /** Rendered small under the plate once systemConfig lands. It usually
   *  arrives mid-intro, so it fades in on its own rather than holding
   *  anything back. */
  version?: string
}

/** A short boot identity before the existing first-run / release notes dialog. */
export function HocusPocusIntro({ onComplete, version }: HocusPocusIntroProps) {
  const { t } = useUiTranslation('shell')
  const [leaving, setLeaving] = useState(false)
  const [ready, setReady] = useState(false)
  const artRef = useRef<HTMLImageElement>(null)
  const onCompleteRef = useRef(onComplete)
  const finishedRef = useRef(false)
  // Kept in an effect rather than assigned during render: the timers below
  // only ever fire after commit, so they always read the latest callback.
  useEffect(() => { onCompleteRef.current = onComplete })

  // Read once: a mid-intro OS change would restart the timeline, which is
  // exactly the jolt the preference asks us to avoid.
  const [holdMs] = useState(() => (
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      ? INTRO_REDUCED_DURATION_MS
      : INTRO_DURATION_MS
  ))
  // Same reasoning: a resize that crossed the budget mid-plate would
  // swap effects in and out under the viewer.
  const [tier] = useState(introQualityTier)

  const finish = useCallback(() => {
    if (finishedRef.current) return
    finishedRef.current = true
    setLeaving(true)
    window.setTimeout(() => onCompleteRef.current(), INTRO_FADE_MS)
  }, [])

  // Readiness gate. The key art is the plate, so the countdown starts
  // when it can be painted — otherwise a cold cache spends the first
  // second on an empty screen and the art lands after its own entrance.
  useEffect(() => {
    let cancelled = false
    const settle = () => { if (!cancelled) setReady(true) }
    const pending: Promise<unknown>[] = []
    const art = artRef.current
    if (art?.decode) pending.push(art.decode().catch(() => {}))
    // Absent in jsdom, and in any browser that refused the font.
    const fonts = document.fonts as FontFaceSet | undefined
    if (fonts?.ready) pending.push(Promise.resolve(fonts.ready).catch(() => {}))
    void Promise.all(pending).then(settle)
    const cap = window.setTimeout(settle, INTRO_ASSET_TIMEOUT_MS)
    return () => {
      cancelled = true
      window.clearTimeout(cap)
    }
  }, [])

  useEffect(() => {
    if (!ready) return
    const fadeTimer = window.setTimeout(() => setLeaving(true), holdMs)
    const doneTimer = window.setTimeout(() => {
      if (finishedRef.current) return
      finishedRef.current = true
      onCompleteRef.current()
    }, holdMs + INTRO_FADE_MS)
    return () => {
      window.clearTimeout(fadeTimer)
      window.clearTimeout(doneTimer)
    }
  }, [ready, holdMs])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') finish()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [finish])

  return (
    <section
      aria-label={t('intro.aria')}
      onClick={finish}
      data-run={ready ? 'true' : 'false'}
      data-leaving={leaving ? 'true' : 'false'}
      data-tier={tier}
      style={{ '--hp-intro-fade': `${INTRO_FADE_MS}ms` } as CSSProperties}
      className="hp-intro-root fixed inset-0 z-[200] isolate overflow-hidden bg-[#07060b]"
    >
      <div className="hp-intro-stage absolute inset-0">
        <div className="hp-intro-artbox" aria-hidden="true">
          <div className="hp-intro-bloom" />
          <div className="hp-intro-art-frame">
            <picture>
              <source srcSet="/hocuspocus/scribe-keyart.webp" type="image/webp" />
              <img
                ref={artRef}
                src="/hocuspocus/scribe-keyart.png"
                alt=""
                fetchPriority="high"
                draggable={false}
                className="hp-intro-art"
              />
            </picture>
          </div>
          {/* In front of the art: embers read as air between the camera
              and the desk, not as specks stuck behind the scribe. */}
          {MOTES.map(mote => (
            <span
              key={`${mote.left}-${mote.top}`}
              className="hp-intro-mote"
              style={{
                left: mote.left,
                top: mote.top,
                '--mote-duration': mote.duration,
                '--mote-delay': mote.delay,
                '--mote-drift': mote.drift,
              } as CSSProperties}
            />
          ))}
        </div>
        <div className="hp-intro-scrim" aria-hidden="true" />

        {/* Copy sits opposite the figure: right column on wide windows,
            stacked above the art when there is no room for two columns.
            Ragged-right inside that column rather than right-aligned —
            the tagline is a sentence, not a label. */}
        <div className="absolute inset-0 flex flex-col items-center justify-start px-8 pt-[13dvh] text-center lg:items-end lg:justify-center lg:pt-0 lg:pr-[7vw] lg:text-left">
          <div className="flex max-w-md flex-col items-center lg:max-w-[min(32rem,42vw)] lg:items-start">
            <img
              src="/hocuspocus-icon.png"
              alt=""
              draggable={false}
              style={{ animationDelay: '420ms' }}
              className="hp-intro-beat h-16 w-16 object-contain drop-shadow-[0_0_32px_rgba(255,176,84,0.45)]"
            />
            <p
              style={{ animationDelay: '700ms' }}
              className="hp-intro-beat mt-6 text-[10px] font-semibold uppercase tracking-[0.46em] text-amber-100/70"
            >
              {t('intro.tagline')}
            </p>
            {/* aria-label carries the name so the split into glyphs stays
                purely visual. The shadow lives in CSS as a text-shadow:
                a `filter` on this element would force its animating
                children into one render surface and repaint the whole
                word every frame. */}
            <h1
              aria-label={WORDMARK}
              className="hp-wordmark hp-intro-wordmark mt-3 text-[clamp(2.75rem,7vw,5.5rem)] font-semibold leading-[0.95] text-white"
            >
              {[...WORDMARK].map((glyph, index) => (
                <span
                  key={`${glyph}-${index}`}
                  className="hp-intro-glyph"
                  style={{
                    animationDelay: `${WORDMARK_DELAY_MS + index * WORDMARK_STAGGER_MS}ms`,
                    '--hp-glyph-offset': `${(
                      (index - (WORDMARK.length - 1) / 2) * WORDMARK_TRACKING_EM
                    ).toFixed(3)}em`,
                  } as CSSProperties}
                >
                  {glyph}
                </span>
              ))}
            </h1>
            <div
              aria-hidden="true"
              style={{ animationDelay: '1500ms' }}
              className="hp-intro-rule mt-5 h-px w-40 bg-gradient-to-r from-amber-200/70 via-amber-200/25 to-transparent"
            />
            <p
              style={{ animationDelay: '1750ms' }}
              className="hp-intro-beat mt-5 max-w-sm text-sm leading-relaxed text-amber-50/70"
            >
              {t('intro.body')}
            </p>
          </div>
        </div>

        <div className="hp-intro-grain" aria-hidden="true" />
      </div>

      {version && (
        <span
          style={{ animationDelay: '2100ms' }}
          className="hp-intro-beat absolute bottom-6 left-6 text-[11px] tracking-wide text-white/35"
        >
          v{version}
        </span>
      )}

      <button
        type="button"
        onClick={finish}
        className="absolute bottom-6 right-6 flex items-center gap-1.5 rounded-full border border-white/15 bg-black/20 px-3 py-1.5 text-[11px] text-white/70 backdrop-blur transition hover:border-amber-200/60 hover:text-white"
      >
        <SkipForward size={13} /> {t('intro.skip')}
      </button>

      {/* Draws across the full width over exactly the hold time, so the
          automatic dismissal reads as a finish rather than a cut. */}
      <div className="absolute inset-x-0 bottom-0 h-px bg-white/5" aria-hidden="true">
        <div
          style={{ animationDuration: `${holdMs}ms` }}
          className="hp-intro-progress h-full bg-gradient-to-r from-amber-200/50 via-amber-200/80 to-amber-100"
        />
      </div>
    </section>
  )
}
