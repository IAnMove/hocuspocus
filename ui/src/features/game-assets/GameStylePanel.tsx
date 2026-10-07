import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { PaletteEditor } from './PaletteEditor'
import { assetImage, buttonClass, fieldClass, panelClass } from './styles'
import { useGameAssetsStore } from './store'
import type { StyleReference } from './types'

export function GameStylePanel() {
  const { t, i18n } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const presets = useGameAssetsStore(state => state.presets)
  const workspace = useGameAssetsStore(state => state.workspace)
  const styleJob = useGameAssetsStore(state => state.styleJob)
  const patchGame = useGameAssetsStore(state => state.patchGame)
  const applyPreset = useGameAssetsStore(state => state.applyPreset)
  const startStyleSheet = useGameAssetsStore(state => state.startStyleSheet)
  const approveStyle = useGameAssetsStore(state => state.approveStyle)
  const discardSample = useGameAssetsStore(state => state.discardSample)
  const [picked, setPicked] = useState<StyleReference[] | null>(null)
  if (!game) return null
  const style = game.style
  const language = i18n.language.startsWith('es') ? 'es' : 'en'
  const samples = game.assets.filter(asset => asset.id.startsWith('style-sample-'))
  const selected = picked || style.references
  const toggle = (assetId: string, attemptId: string) => {
    const has = selected.some(item => item.assetId === assetId && item.attemptId === attemptId)
    setPicked(has ? selected.filter(item => !(item.assetId === assetId && item.attemptId === attemptId)) : [...selected, { assetId, attemptId }])
  }
  return (
    <div className="space-y-3">
      <div className={`${panelClass} space-y-3`}>
        <label className="block text-sm">
          {t('preset')}
          <select aria-label={t('preset')} className={fieldClass} value={style.preset} onChange={event => applyPreset(event.target.value)}>
            {presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label[language] || preset.id}</option>)}
            {!presets.some(preset => preset.id === style.preset) && <option value={style.preset}>{style.preset}</option>}
          </select>
        </label>
        <div className="flex flex-wrap gap-1" aria-label={t('palette')}>
          {style.palette.slice(0, 16).map(color => <span key={color} className="h-4 w-4 rounded-sm border border-border" style={{ background: color }} />)}
        </div>
        <label className="block text-sm">{t('traits')}<textarea className={fieldClass} rows={3} value={style.traits} onChange={event => patchGame({ style: { traits: event.target.value } })} /></label>
        <label className="block text-sm">{t('negative')}<textarea className={fieldClass} rows={2} value={style.negative} onChange={event => patchGame({ style: { negative: event.target.value } })} /></label>
        <PaletteEditor colors={style.palette} mode={style.paletteMode} maxColors={style.pixel.colors}
          onChange={palette => patchGame({ style: { palette } })} onMode={paletteMode => patchGame({ style: { paletteMode } })} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">{t('tile')}<input className={fieldClass} type="number" min={1} value={style.pixel.tile} onChange={event => patchGame({ style: { pixel: { ...style.pixel, tile: Number(event.target.value) } } })} /></label>
          <label className="block text-sm">{t('colors')}<input className={fieldClass} type="number" min={1} value={style.pixel.colors} onChange={event => patchGame({ style: { pixel: { ...style.pixel, colors: Number(event.target.value) } } })} /></label>
          <label className="block text-sm">{t('outline')}<select aria-label={t('outline')} className={fieldClass} value={style.pixel.outline} onChange={event => patchGame({ style: { pixel: { ...style.pixel, outline: event.target.value } } })}>
            <option value="dark-1px">dark-1px</option><option value="black-1px">black-1px</option><option value="none">none</option>
          </select></label>
          <label className="block text-sm">{t('light')}<select aria-label={t('light')} className={fieldClass} value={style.light} onChange={event => patchGame({ style: { light: event.target.value } })}>
            <option value="top-left">top-left</option><option value="top">top</option><option value="front">front</option>
          </select></label>
          <label className="block text-sm">{t('screen')}<select aria-label={t('screen')} className={fieldClass} value={style.screen} onChange={event => patchGame({ style: { screen: event.target.value } })}>
            <option value="auto">auto</option><option value="green">green</option><option value="magenta">magenta</option>
          </select></label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">{t('audioGenre')}<input className={fieldClass} value={style.audio.genre} onChange={event => patchGame({ style: { audio: { ...style.audio, genre: event.target.value } } })} /></label>
          <label className="block text-sm">{t('instruments')}<input className={fieldClass} value={style.audio.instruments} onChange={event => patchGame({ style: { audio: { ...style.audio, instruments: event.target.value } } })} /></label>
          <label className="block text-sm">{t('bpmMin')}<input className={fieldClass} type="number" min={1} value={style.audio.bpm[0]} onChange={event => patchGame({ style: { audio: { ...style.audio, bpm: [Number(event.target.value), style.audio.bpm[1]] } } })} /></label>
          <label className="block text-sm">{t('bpmMax')}<input className={fieldClass} type="number" min={1} value={style.audio.bpm[1]} onChange={event => patchGame({ style: { audio: { ...style.audio, bpm: [style.audio.bpm[0], Number(event.target.value)] } } })} /></label>
          <label className="block text-sm">{t('lufs')}<input className={fieldClass} type="number" value={style.audio.musicLufs} onChange={event => patchGame({ style: { audio: { ...style.audio, musicLufs: Number(event.target.value) } } })} /></label>
        </div>
        <button type="button" className={buttonClass} onClick={() => { void startStyleSheet() }}>{t('styleSheet')}</button>
        {styleJob && <p className="text-sm">{t('styleProgress', { status: styleJob.status })}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {samples.map(asset => {
          const image = assetImage(asset, workspace)
          return (
            <article key={asset.id} className={panelClass}>
              <h3 className="text-sm font-medium">{asset.name}</h3>
              {image && <img src={image} alt={asset.name} className="mt-2 h-24 w-24 object-contain" style={{ imageRendering: style.pixel.enabled ? 'pixelated' : 'auto' }} />}
              <ul className="mt-2 space-y-1">
                {asset.attempts.map(attempt => (
                  <li key={attempt.id} className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{attempt.id}</span>
                    <button type="button" className={buttonClass} aria-pressed={selected.some(item => item.assetId === asset.id && item.attemptId === attempt.id)}
                      onClick={() => toggle(asset.id, attempt.id)}>{t('useReference')}</button>
                    <button type="button" className={buttonClass} onClick={() => { void discardSample(asset.id, attempt.id, t('discardNote')) }}>{t('discardReference')}</button>
                  </li>
                ))}
              </ul>
            </article>
          )
        })}
      </div>
      {!samples.length && <p className="text-sm text-muted-foreground">{t('noSamples')}</p>}
      <p className="text-sm">{t('approveStyleWarning')}</p>
      <button type="button" className={buttonClass} disabled={!selected.length} onClick={() => { void approveStyle(selected) }}>{t('approveStyle')}</button>
    </div>
  )
}
