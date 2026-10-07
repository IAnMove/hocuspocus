import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { buttonClass, colorsFromImageData, errorClass, fieldClass, isHexColor } from './styles'
import type { PaletteMode } from './types'

/** Every swatch is shown; adding and extracting stop at ``maxColors``. */
export function PaletteEditor({ colors, mode, maxColors, onChange, onMode }: {
  colors: string[]
  mode: PaletteMode
  maxColors: number
  onChange: (colors: string[]) => void
  onMode: (mode: PaletteMode) => void
}) {
  const { t } = useUiTranslation('gameAssets')
  const [draft, setDraft] = useState('#')
  const [invalid, setInvalid] = useState(false)
  const [failed, setFailed] = useState(false)
  const limit = Math.max(1, maxColors || 16)
  const full = colors.length >= limit

  const add = () => {
    const next = draft.trim().toLowerCase()
    if (!isHexColor(next)) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    if (!colors.includes(next) && !full) onChange([...colors, next])
    setDraft('#')
  }

  const extract = async (input: HTMLInputElement) => {
    const file = input.files?.[0]
    input.value = '' // the same image can be picked again
    if (!file) return
    setFailed(false)
    try {
      const bitmap = await createImageBitmap(file)
      const canvas = document.createElement('canvas')
      canvas.width = bitmap.width
      canvas.height = bitmap.height
      const context = canvas.getContext('2d')
      if (!context) throw new Error('canvas')
      context.drawImage(bitmap, 0, 0)
      onChange(colorsFromImageData(context.getImageData(0, 0, bitmap.width, bitmap.height).data, limit))
    } catch {
      setFailed(true)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('palette')}>
        {colors.map((color, index) => (
          <button key={`${color}-${index}`} type="button" className="h-8 w-8 rounded border border-border" style={{ background: color }}
            aria-label={`${t('removeColor')} ${color}`} onClick={() => onChange(colors.filter((_, item) => item !== index))} />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{t('paletteCount', { count: colors.length, max: limit })}</p>
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label={t('hex')} className={`${fieldClass} max-w-[8rem]`} value={draft} onChange={event => { setDraft(event.target.value); setInvalid(false) }} />
        <button type="button" className={buttonClass} disabled={full} onClick={add}>{t('addColor')}</button>
        <label className={buttonClass}>
          {t('extract')}
          <input className="sr-only" type="file" accept="image/png,image/webp,image/jpeg" onChange={event => { void extract(event.currentTarget) }} />
        </label>
        <label className="text-sm">
          {t('paletteMode')}
          <select aria-label={t('paletteMode')} className={`${fieldClass} ml-2 w-auto`} value={mode} onChange={event => onMode(event.target.value as PaletteMode)}>
            <option value="locked">{t('locked')}</option>
            <option value="free">{t('free')}</option>
          </select>
        </label>
      </div>
      {invalid && <p className={errorClass} role="alert">{t('invalidHex')}</p>}
      {failed && <p className={errorClass} role="alert">{t('extractFailed')}</p>}
    </div>
  )
}
