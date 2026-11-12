import { useState } from 'react'
import { MAX_ANSWER } from './model'
import { guideInput } from './styles'

/** Keep the user's trailing newline while a canonical list is normalized during autosave. */
export function WritingAnswer({ value, question, hint, placeholder, onChange }: {
  value: string; question: string; hint: string; placeholder: string; onChange: (value: string) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  return <label className="block space-y-2 text-sm text-text-primary">
    <span className="font-medium">{question}</span>
    <span className="block text-xs text-text-muted">{hint}</span>
    <textarea aria-label={question} className={guideInput} rows={4} maxLength={MAX_ANSWER}
      value={draft ?? value} placeholder={placeholder} onFocus={() => setDraft(value)} onBlur={() => setDraft(null)}
      onChange={event => { setDraft(event.target.value); onChange(event.target.value) }} />
  </label>
}
