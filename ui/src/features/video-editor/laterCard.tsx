import { useLayoutEffect, useRef } from 'react'
import { useUiTranslation } from '../../i18n'
import type { InterstitialTransition } from './editorTimeline'

function FittedCardText({
  text,
  textSize,
  baseSize,
  boxClassName,
  className,
}: {
  text: string
  textSize: number
  baseSize: number
  boxClassName: string
  className: string
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLParagraphElement>(null)

  useLayoutEffect(() => {
    const box = boxRef.current
    const textElement = textRef.current
    if (!box || !textElement) return

    const fit = () => {
      const availableWidth = box.clientWidth
      const availableHeight = box.clientHeight
      if (!availableWidth || !availableHeight) return

      const scale = Math.max(50, Math.min(160, textSize)) / 100
      const target = Math.max(7, Math.min(availableWidth, availableHeight) * baseSize * scale)
      let low = 6
      let high = target
      let fitted = low

      for (let attempt = 0; attempt < 10; attempt++) {
        const candidate = (low + high) / 2
        textElement.style.fontSize = `${candidate}px`
        const fits = textElement.scrollWidth <= availableWidth + 1
          && textElement.scrollHeight <= availableHeight + 1
        if (fits) {
          fitted = candidate
          low = candidate
        } else {
          high = candidate
        }
      }
      textElement.style.fontSize = `${fitted}px`
    }

    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(box)
    return () => observer.disconnect()
  }, [baseSize, text, textSize])

  return (
    <div ref={boxRef} className={`flex min-h-0 items-center justify-center ${boxClassName}`}>
      <p
        ref={textRef}
        className={`w-full whitespace-pre-line break-words text-center [overflow-wrap:anywhere] ${className}`}
      >
        {text}
      </p>
    </div>
  )
}

export function LaterCard({
  transition,
  text,
  textSize = 100,
  progress = 0,
  compact = false,
}: {
  transition: InterstitialTransition
  text: string
  textSize?: number
  progress?: number
  compact?: boolean
}) {
  const { t } = useUiTranslation('videoEditor')
  const safeText = text.trim() || t('timeCard.default')
  if (transition === 'later-clock') {
    return (
      <div
        className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#07111f] text-white"
        style={{ backgroundImage: 'radial-gradient(circle at 18% 20%, #224a6b 0, transparent 42%), linear-gradient(145deg, #101f34, #020617 78%)' }}
      >
        <div className={`flex items-center justify-center ${compact ? 'gap-1.5' : 'h-full w-full gap-[clamp(1rem,6vw,5rem)] px-[8%]'}`}>
          <div
            className={`relative shrink-0 rounded-full border-[#fbbf24] shadow-2xl ${compact ? 'h-6 w-6 border-2' : 'h-[clamp(5rem,27vw,17rem)] w-[clamp(5rem,27vw,17rem)] border-[clamp(4px,.8vw,10px)]'}`}
            style={{ backgroundImage: 'radial-gradient(circle, #f8fafc 0 67%, transparent 68%), repeating-conic-gradient(#172554 0deg 1.5deg, #f8fafc 1.5deg 30deg)' }}
          >
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-slate-900 ${compact ? 'h-2 w-[2px]' : 'h-[29%] w-[4%]'}`}
              style={{ transform: 'translate(-50%, -100%) rotate(-48deg)' }}
            />
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-slate-900 ${compact ? 'h-2.5 w-[1px]' : 'h-[39%] w-[3%]'}`}
              style={{ transform: 'translate(-50%, -100%) rotate(28deg)' }}
            />
            <span
              className={`absolute left-1/2 top-1/2 origin-bottom rounded-full bg-red-500 ${compact ? 'h-2.5 w-px' : 'h-[42%] w-[1.5%]'}`}
              style={{ transform: `translate(-50%, -100%) rotate(${132 + progress * 720}deg)` }}
            />
            <span className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-400 ${compact ? 'h-1 w-1' : 'h-[8%] w-[8%]'}`} />
          </div>
          {compact ? (
            <p className="max-w-16 whitespace-pre-line break-words text-center text-[6px] font-semibold leading-tight [overflow-wrap:anywhere]">
              {safeText}
            </p>
          ) : (
            <FittedCardText
              text={safeText}
              textSize={textSize}
              baseSize={0.17}
              boxClassName="h-[64%] w-[42%]"
              className="font-semibold leading-tight drop-shadow-lg"
            />
          )}
        </div>
      </div>
    )
  }

  if (transition === 'later-tropical') {
    return (
      <div
        className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#087f8c]"
        style={{
          backgroundImage: 'radial-gradient(circle at 12% 18%, #f4d35e 0 5%, transparent 5.5%), radial-gradient(circle at 82% 22%, #f95738 0 7%, transparent 7.5%), radial-gradient(circle at 22% 84%, #74c69d 0 8%, transparent 8.5%), radial-gradient(circle at 91% 78%, #ee964b 0 6%, transparent 6.5%), repeating-linear-gradient(42deg, transparent 0 34px, rgba(7,59,76,.2) 35px 38px)'
        }}
      >
        <div className={`${compact ? 'inset-1 rounded' : 'inset-[9%] rounded-[clamp(1rem,4vw,3rem)] border-[clamp(2px,.5vw,7px)]'} absolute border border-[#f6f7d7]/85 bg-[#043b44]/75 shadow-2xl`} />
        {compact ? (
          <p className="relative max-w-[76%] -rotate-1 whitespace-pre-line break-words text-center text-[6px] font-black uppercase leading-[.95] text-[#f6f7d7] [overflow-wrap:anywhere]" style={{ textShadow: '1px 1px #073b4c' }}>
            {safeText}
          </p>
        ) : (
          <FittedCardText
            text={safeText}
            textSize={textSize}
            baseSize={0.21}
            boxClassName="relative h-[48%] w-[72%]"
            className="-rotate-1 font-black uppercase leading-[.95] text-[#f6f7d7] [text-shadow:clamp(2px,.5vw,8px)_clamp(2px,.5vw,8px)_#073b4c]"
          />
        )}
      </div>
    )
  }

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#170f0a] text-[#f4e8ce]"
      style={{ backgroundImage: 'radial-gradient(ellipse at center, #382517 0, #170f0a 60%, #090604 100%)' }}
    >
      <div className={`absolute border border-[#c9a96e] ${compact ? 'inset-1' : 'inset-[7%]'}`} />
      <div className={`absolute border border-[#685238] ${compact ? 'inset-1.5' : 'inset-[10%]'}`} />
      {compact ? (
        <p className="relative max-w-[72%] whitespace-pre-line break-words text-center text-[5px] font-serif font-semibold uppercase leading-tight tracking-[.12em] [overflow-wrap:anywhere]">
          {safeText}
        </p>
      ) : (
        <FittedCardText
          text={safeText}
          textSize={textSize}
          baseSize={0.21}
          boxClassName="relative h-[38%] w-[68%]"
          className="font-serif font-semibold uppercase leading-tight tracking-[.12em]"
        />
      )}
    </div>
  )
}
