import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel } from './gameErrors'
import { NumberField } from './gameUi'
import { PaletteEditor } from './PaletteEditor'
import { attemptImage, buttonClass, fieldClass, panelClass, usableAttempt } from './styles'
import { useGameAssetsStore } from './store'
import { isActiveJob } from './storeModel'
import type { Game, GameStyle, StylePatch, StyleReference } from './types'

const OUTLINES = ['dark-1px', 'black-1px', 'none'] as const
const LIGHTS = ['top-left', 'top', 'front'] as const
const SCREENS = ['auto', 'green', 'magenta'] as const

function referenceKey(ref: StyleReference): string {
  return `${ref.assetId}/${ref.attemptId}`
}

/** Attempts that may be references: ok and not rejected, on any asset of the game. */
function usableReferences(game: Game): Set<string> {
  const keys = new Set<string>()
  for (const asset of game.assets) {
    for (const attempt of asset.attempts) if (usableAttempt(attempt)) keys.add(referenceKey({ assetId: asset.id, attemptId: attempt.id }))
  }
  return keys
}

export function GameStylePanel() {
  const game = useGameAssetsStore(state => state.game)
  if (!game) return null
  return (
    <div className="space-y-3">
      <StyleFields style={game.style} />
      <StyleSamples game={game} />
    </div>
  )
}

function StyleFields({ style }: { style: GameStyle }) {
  const { t, i18n } = useUiTranslation('gameAssets')
  const presets = useGameAssetsStore(state => state.presets)
  const styleJob = useGameAssetsStore(state => state.styleJob)
  const patchGame = useGameAssetsStore(state => state.patchGame)
  const applyPreset = useGameAssetsStore(state => state.applyPreset)
  const startStyleSheet = useGameAssetsStore(state => state.startStyleSheet)
  const language = i18n.language.startsWith('es') ? 'es' : 'en'
  const patchStyle = (patch: StylePatch) => patchGame({ style: patch })
  return (
    <div className={`${panelClass} space-y-3`}>
      <label className="block text-sm">
        {t('preset')}
        <select aria-label={t('preset')} className={fieldClass} value={style.preset}
          onChange={event => { if (event.target.value !== style.preset) void applyPreset(event.target.value) }}>
          {presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label[language] || preset.id}</option>)}
          {!presets.some(preset => preset.id === style.preset) && <option value={style.preset}>{style.preset}</option>}
        </select>
      </label>
      <label className="block text-sm">{t('traits')}<textarea className={fieldClass} rows={3} value={style.traits} onChange={event => patchStyle({ traits: event.target.value })} /></label>
      <label className="block text-sm">{t('negative')}<textarea className={fieldClass} rows={2} value={style.negative} onChange={event => patchStyle({ negative: event.target.value })} /></label>
      <PaletteEditor colors={style.palette} mode={style.paletteMode} maxColors={style.pixel.colors}
        onChange={palette => patchStyle({ palette })} onMode={paletteMode => patchStyle({ paletteMode })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <NumberField label={t('tile')} min={1} value={style.pixel.tile} onValue={tile => patchStyle({ pixel: { tile } })} />
        <NumberField label={t('colors')} min={1} value={style.pixel.colors} onValue={colors => patchStyle({ pixel: { colors } })} />
        <label className="block text-sm">{t('outline')}<select aria-label={t('outline')} className={fieldClass} value={style.pixel.outline} onChange={event => patchStyle({ pixel: { outline: event.target.value } })}>
          {OUTLINES.map(item => <option key={item} value={item}>{t(`outlines.${item}`)}</option>)}
        </select></label>
        <label className="block text-sm">{t('light')}<select aria-label={t('light')} className={fieldClass} value={style.light} onChange={event => patchStyle({ light: event.target.value })}>
          {LIGHTS.map(item => <option key={item} value={item}>{t(`lights.${item}`)}</option>)}
        </select></label>
        <label className="block text-sm">{t('screen')}<select aria-label={t('screen')} className={fieldClass} value={style.screen} onChange={event => patchStyle({ screen: event.target.value })}>
          {SCREENS.map(item => <option key={item} value={item}>{t(`screens.${item}`)}</option>)}
        </select></label>
      </div>
      <AudioFields style={style} onPatch={patchStyle} />
      <button type="button" className={buttonClass} disabled={isActiveJob(styleJob)}
        onClick={() => { void startStyleSheet() }}>{t('styleSheet')}</button>
      {styleJob && <p className="text-sm" aria-live="polite">{t('styleProgress', { status: codeLabel('jobStatuses', styleJob.status) })}</p>}
    </div>
  )
}

function AudioFields({ style, onPatch }: { style: GameStyle; onPatch: (patch: StylePatch) => void }) {
  const { t } = useUiTranslation('gameAssets')
  const audio = style.audio
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block text-sm">{t('audioGenre')}<input className={fieldClass} value={audio.genre} onChange={event => onPatch({ audio: { genre: event.target.value } })} /></label>
      <label className="block text-sm">{t('instruments')}<input className={fieldClass} value={audio.instruments} onChange={event => onPatch({ audio: { instruments: event.target.value } })} /></label>
      <NumberField label={t('bpmMin')} min={1} value={audio.bpm[0]} onValue={value => onPatch({ audio: { bpm: [value, audio.bpm[1]] } })} />
      <NumberField label={t('bpmMax')} min={1} value={audio.bpm[1]} onValue={value => onPatch({ audio: { bpm: [audio.bpm[0], value] } })} />
      <NumberField label={t('lufs')} min={-70} value={audio.musicLufs} onValue={musicLufs => onPatch({ audio: { musicLufs } })} />
    </div>
  )
}

function StyleSamples({ game }: { game: Game }) {
  const { t } = useUiTranslation('gameAssets')
  const workspace = useGameAssetsStore(state => state.workspace)
  const approveStyle = useGameAssetsStore(state => state.approveStyle)
  const discardSample = useGameAssetsStore(state => state.discardSample)
  // The pick belongs to one game; another game starts from its own references.
  const [picked, setPicked] = useState<{ gameId: string; refs: StyleReference[] } | null>(null)
  const usable = usableReferences(game)
  const base = picked?.gameId === game.id ? picked.refs : game.style.references
  const selected = base.filter(ref => usable.has(referenceKey(ref)))
  const isSelected = (ref: StyleReference) => selected.some(item => referenceKey(item) === referenceKey(ref))
  const toggle = (ref: StyleReference) => setPicked({
    gameId: game.id,
    refs: isSelected(ref) ? selected.filter(item => referenceKey(item) !== referenceKey(ref)) : [...selected, ref],
  })
  const approve = async () => {
    if (await approveStyle(selected)) setPicked(null)
  }
  const tiles = game.assets
    .filter(asset => asset.id.startsWith('style-sample-'))
    .flatMap(asset => asset.attempts.filter(usableAttempt).map(attempt => ({ asset, attempt })))
  return (
    <>
      <ul className="grid gap-3 sm:grid-cols-2">
        {tiles.map(({ asset, attempt }) => {
          const ref = { assetId: asset.id, attemptId: attempt.id }
          const image = attemptImage(attempt, workspace)
          return (
            <li key={referenceKey(ref)} className={panelClass}>
              <h3 className="text-sm font-medium">{asset.name} · <span className="font-mono">{attempt.id}</span></h3>
              {image && <img src={image} alt={`${asset.name} ${attempt.id}`} className="mt-2 h-24 w-24 object-contain" style={{ imageRendering: game.style.pixel.enabled ? 'pixelated' : 'auto' }} />}
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" className={buttonClass} aria-pressed={isSelected(ref)} aria-label={t('useReferenceFor', { id: attempt.id })}
                  onClick={() => toggle(ref)}>{t('useReference')}</button>
                <button type="button" className={buttonClass} aria-label={t('discardReferenceFor', { id: attempt.id })}
                  onClick={() => { void discardSample(asset.id, attempt.id, t('discardNote')) }}>{t('discardReference')}</button>
              </div>
            </li>
          )
        })}
      </ul>
      {!tiles.length && <p className="text-sm text-muted-foreground">{t('noSamples')}</p>}
      <p className="text-sm">{t('approveStyleWarning')}</p>
      <button type="button" className={buttonClass} disabled={!selected.length} onClick={() => { void approve() }}>{t('approveStyle')}</button>
    </>
  )
}
