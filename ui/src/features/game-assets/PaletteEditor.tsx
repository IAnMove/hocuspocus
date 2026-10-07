import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { buttonClass, colorsFromImageData, fieldClass, isHexColor } from './styles'
import type { PaletteMode } from './types'

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

  const add = () => {
    const next = draft.trim().toLowerCase()
    if (!isHexColor(next)) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    if (!colors.includes(next)) onChange([...colors, next])
    setDraft('#')
  }

  const extract = async (file: File | undefined) => {
    if (!file) return
    const bitmap = await createImageBitmap(file)
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const context = canvas.getContext('2d')
    if (!context) return
    context.drawImage(bitmap, 0, 0)
    onChange(colorsFromImageData(context.getImageData(0, 0, bitmap.width, bitmap.height).data, maxColors || colors.length || 16))
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {colors.map((color, index) => (
          <button key={`${color}-${index}`} type="button" className="h-8 w-8 rounded border border-border" style={{ background: color }}
            aria-label={`${t('removeColor')} ${color}`} onClick={() => onChange(colors.filter((_, item) => item !== index))} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label={t('hex')} className={`${fieldClass} max-w-[8rem]`} value={draft} onChange={event => { setDraft(event.target.value); setInvalid(false) }} />
        <button type="button" className={buttonClass} onClick={add}>{t('addColor')}</button>
        <label className={buttonClass}>
          {t('extract')}
          <input className="sr-only" type="file" accept="image/png,image/webp,image/jpeg" onChange={event => { void extract(event.target.files?.[0]) }} />
        </label>
        <label className="text-sm">
          {t('paletteMode')}
          <select aria-label={t('paletteMode')} className={`${fieldClass} ml-2 w-auto`} value={mode} onChange={event => onMode(event.target.value as PaletteMode)}>
            <option value="locked">{t('locked')}</option>
            <option value="free">{t('free')}</option>
          </select>
        </label>
      </div>
      {invalid && <p className="text-sm text-red-500">{t('invalidHex')}</p>}
    </div>
  )
}
