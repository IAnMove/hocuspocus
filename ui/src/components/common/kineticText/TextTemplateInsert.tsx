import { useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import { buildTextTemplate, importLyricsText, parseSceneLyrics, TEXT_TEMPLATES, type KineticText, type SceneLyrics } from '../../../lib/kineticText'
import { randomUuid } from '../../../lib/uuid'
import { fieldClass } from './textFields'

export function TextTemplateInsert({ duration, width, height, disabled, onInsert, onLyrics }: {
  duration: number
  width: number
  height: number
  disabled?: boolean
  onInsert: (cues: KineticText[]) => void
  onLyrics?: (lyrics: SceneLyrics | undefined) => void
}) {
  const { t } = useUiTranslation('kineticText')
  const [templateId, setTemplateId] = useState(TEXT_TEMPLATES[0].id)
  const template = TEXT_TEMPLATES.find(item => item.id === templateId) ?? TEXT_TEMPLATES[0]
  const [values, setValues] = useState<Record<string, string>>({})
  const [lyricsText, setLyricsText] = useState('')
  const [offset, setOffset] = useState(0)
  const value = (key: string, fallback: string) => values[key] ?? fallback
  return <div className="space-y-2 rounded border border-border p-2">
    <div className="text-xs font-semibold">{t('insertTemplate')}</div>
    <select value={templateId} onChange={event => { setTemplateId(event.target.value); setValues({}) }} className={fieldClass} disabled={disabled}>
      {TEXT_TEMPLATES.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
    </select>
    {template.fields.map(item => <label key={item.key} className="block text-xs">{item.key}<input value={value(item.key, item.default)} onChange={event => setValues(current => ({ ...current, [item.key]: event.target.value }))} className={fieldClass} disabled={disabled} /></label>)}
    <button type="button" disabled={disabled} className="min-h-9 rounded border border-cyan-400/40 px-3 text-xs text-cyan-200" onClick={() => {
      const filled = Object.fromEntries(template.fields.map(item => [item.key, value(item.key, item.default)]))
      onInsert(buildTextTemplate(template.id, filled, { start: 0, duration: Math.min(4, duration), width, height }).map(cue => ({ ...cue, id: randomUuid() })))
    }}>{t('insertTemplate')}</button>
    {onLyrics ? <label className="block text-xs">{t('lyricsPaste')}<textarea value={lyricsText} onChange={event => setLyricsText(event.target.value)} className={fieldClass} rows={4} disabled={disabled} /><input type="number" step={0.1} value={offset} onChange={event => setOffset(event.target.valueAsNumber || 0)} className={fieldClass} disabled={disabled} />
      <button type="button" disabled={disabled} className="mt-2 min-h-9 rounded border border-border px-3 text-xs" onClick={() => {
        const lines = importLyricsText(lyricsText, duration, offset)
        onLyrics(parseSceneLyrics({ mode: 'karaoke', lines, style: { font: 'sans', size: 7, color: '#f4efe6', activeColor: '#ffe08a', x: 50, y: 78, maxWidth: 80, align: 'center', visibleLines: 2 } }))
      }}>{t('lyricsImport')}</button></label> : null}
  </div>
}
