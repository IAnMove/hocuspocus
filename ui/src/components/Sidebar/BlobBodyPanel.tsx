import { useEffect, useState } from 'react'
import { fetchBlobPresets, makeBlob, type BlobPresetCatalog } from '../../api/blobBody'
import { controlReason } from '../../i18n/controlLabel'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'

const FIELD = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1 text-xs text-text-primary'

function applyCatalogPreset(catalog: BlobPresetCatalog, name: string) {
  const preset = catalog.presets[name] || {}
  return {
    height: preset.height ?? catalog.height.default,
    build: preset.build || 'average',
    family: preset.family || 'blob',
    hairStyle: preset.hair?.style || 'none',
    headWidth: preset.head?.width ?? catalog.head.default.width,
    hands: preset.hands || 'ball',
    feet: preset.feet || 'shoe',
  }
}

export function BlobBodyPanel() {
  const { t } = useUiTranslation('studio')
  const workspace = useStore(state => state.activeWorkspace)
  const mediaFilter = useStore(state => state.mediaFilter)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const maybeRefreshGallery = useStore(state => state.maybeRefreshGallery)
  const setSelectedOutput = useStore(state => state.setSelectedOutput)
  const [catalog, setCatalog] = useState<BlobPresetCatalog | null>(null)
  const [preset, setPreset] = useState('')
  const [name, setName] = useState(() => t('makers.defaultBlob'))
  const [height, setHeight] = useState(1.8)
  const [build, setBuild] = useState('average')
  const [family, setFamily] = useState('blob')
  const [hairStyle, setHairStyle] = useState('none')
  const [headWidth, setHeadWidth] = useState(0.31)
  const [hands, setHands] = useState('ball')
  const [feet, setFeet] = useState('shoe')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [made, setMade] = useState<string | null>(null)

  useEffect(() => {
    fetchBlobPresets().then(setCatalog).catch(err => {
      setError(err instanceof Error ? err.message : t('makers.blobPresetsFailed'))
    })
  }, [])

  const choosePreset = (next: string) => {
    setPreset(next)
    if (!catalog || !next) return
    const applied = applyCatalogPreset(catalog, next)
    setHeight(applied.height)
    setBuild(applied.build)
    setFamily(applied.family)
    setHairStyle(applied.hairStyle)
    setHeadWidth(applied.headWidth)
    setHands(applied.hands)
    setFeet(applied.feet)
    setName(next)
  }

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await makeBlob({
        workspace, name: name.trim() || t('makers.defaultBlob'), preset: preset || undefined,
        height, build, family, hairStyle, headWidth, hands, feet,
      })
      if (mediaFilter !== 'model3d') setMediaFilter('model3d')
      await maybeRefreshGallery({ message: t('makers.blobReady'), force: true })
      setSelectedOutput(0)
      setMade(result.rigged_file)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('makers.blobFailed'))
    } finally {
      setBusy(false)
    }
  }

  const builds = catalog?.build || ['slim', 'average', 'round', 'pear']
  const families = catalog?.family || ['blob', 'anime', 'chibi']
  const hairStyles = catalog?.hair?.style || ['none', 'short', 'bangs', 'spiky', 'long', 'ponytail', 'twin_tails', 'bun']
  const handChoices = catalog?.hands || ['ball', 'mitten']
  const footChoices = catalog?.feet || ['shoe', 'ball', 'boot']
  const headLimits = catalog?.head.limits.width || [0.12, 0.46]
  const blocked = busy || !workspace
  return (
    <section className="rounded-lg border border-border p-3 flex flex-col gap-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{t('makers.blobTitle')}</h3>
      <label className="text-[10px] text-text-muted">{t('makers.name')}
        <input className={FIELD} value={name} maxLength={64} onChange={event => setName(event.target.value)} />
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.preset')}
        <select className={FIELD} value={preset} onChange={event => choosePreset(event.target.value)}>
          <option value="">{t('makers.custom')}</option>
          {Object.keys(catalog?.presets || {}).map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.height', { value: height.toFixed(2) })}
        <input type="range" min={1.2} max={2.2} step={0.01} value={height} onChange={event => setHeight(Number(event.target.value))} />
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.build')}
        <select className={FIELD} value={build} onChange={event => setBuild(event.target.value)}>
          {builds.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.family')}
        <select className={FIELD} value={family} onChange={event => setFamily(event.target.value)}>
          {families.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.hair')}
        <select className={FIELD} value={hairStyle} onChange={event => setHairStyle(event.target.value)}>
          {hairStyles.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.headWidth', { value: headWidth.toFixed(2) })}
        <input type="range" min={headLimits[0]} max={headLimits[1]} step={0.01} value={headWidth} onChange={event => setHeadWidth(Number(event.target.value))} />
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.hands')}
        <select className={FIELD} value={hands} onChange={event => setHands(event.target.value)}>
          {handChoices.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">{t('makers.feet')}
        <select className={FIELD} value={feet} onChange={event => setFeet(event.target.value)}>
          {footChoices.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <button type="button" disabled={blocked} title={controlReason(blocked, 'disabled.actionInProgress')} onClick={() => void create()} className={`w-full px-4 py-2 rounded-lg text-xs font-medium ${busy ? 'bg-bg-tertiary text-text-muted' : 'bg-cta text-white'}`}>
        {busy ? '…' : t('makers.create')}
      </button>
      {error && <p className="text-[10px] text-red-300">{error}</p>}
      {made && <p className="text-[10px] text-text-secondary">{made}</p>}
    </section>
  )
}
