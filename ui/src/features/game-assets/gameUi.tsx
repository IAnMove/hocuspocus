import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel, problemText } from './gameErrors'
import { estimateSource, formatMinutes } from './listModel'
import { errorClass, fieldClass } from './styles'
import type { GameEstimate, GameProblem } from './types'

/** Every problem with its line; a whole-list problem (line 0) prints no line. */
export function ProblemList({ problems }: { problems: GameProblem[] }) {
  if (!problems.length) return null
  return (
    <ul className="space-y-1">
      {problems.map((problem, index) => (
        <li key={`${problem.line ?? 0}-${problem.code ?? ''}-${index}`} className={errorClass}>{problemText(problem)}</li>
      ))}
    </ul>
  )
}

export function ErrorNotice({ error, problems = [] }: { error: string | null | undefined; problems?: GameProblem[] }) {
  if (!error && !problems.length) return null
  return (
    <div role="alert" className="mb-2 space-y-1">
      {error && <p className={errorClass}>{error}</p>}
      <ProblemList problems={problems} />
    </div>
  )
}

export function EstimateSummary({ estimate }: { estimate: GameEstimate }) {
  const { t, i18n } = useUiTranslation('gameAssets')
  const source = estimateSource(estimate.source)
  const label = source === 'history' ? t('sourceHistory') : source === 'trial' ? t('sourceTrial') : t('sourceDefaults')
  const minutes = (value: number) => formatMinutes(value, i18n.language)
  return (
    <div className="space-y-1 text-sm">
      <p>{t('estimate', { minutes: minutes(estimate.minutes) })} · {label}</p>
      {Object.entries(estimate.byKind).map(([kind, value]) => (
        <p key={kind}>{t('estimateKind', { kind: codeLabel('kinds', kind), minutes: minutes(value) })}</p>
      ))}
    </div>
  )
}

/** A number input that keeps what the user types and reports only whole values at or above ``min``. */
export function NumberField({ label, value, min, onValue }: { label: string; value: number; min?: number; onValue: (value: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const change = (text: string) => {
    setDraft(text)
    const number = Number(text)
    if (text.trim() !== '' && Number.isFinite(number) && (min === undefined || number >= min)) onValue(Math.round(number))
  }
  return (
    <label className="block text-sm">
      {label}
      <input className={fieldClass} type="number" min={min} value={draft ?? String(value)}
        onChange={event => change(event.target.value)} onBlur={() => setDraft(null)} />
    </label>
  )
}
