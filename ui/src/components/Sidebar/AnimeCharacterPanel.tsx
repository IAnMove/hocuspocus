import { useState } from 'react'
import { makeAnime } from '../../api/blobBody'
import { controlReason } from '../../i18n/controlLabel'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'

const FIELD = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1 text-xs text-text-primary'
const GENDERS = ['girl', 'boy', 'man']
const BODIES = ['slim', 'average', 'tall']
const HAIR = ['none', 'short', 'bangs', 'bob', 'long', 'twin_tails', 'spiky', 'ponytail', 'bun']
const OUTFITS = ['school', 'casual', 'sport']
const FACE_SOURCES = ['program', 'qwen']
const FACE_STYLES = ['anime', 'cute']
const FACE_SHAPES = ['soft', 'sharp']

/** One anime 3D character from traits: the same `model3d.anime.make` the Wizard and MCP call. */
export function AnimeCharacterPanel() {
  const { t } = useUiTranslation('studio')
  const workspace = useStore(state => state.activeWorkspace)
  const mediaFilter = useStore(state => state.mediaFilter)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const maybeRefreshGallery = useStore(state => state.maybeRefreshGallery)
  const setSelectedOutput = useStore(state => state.setSelectedOutput)
  const [name, setName] = useState(() => t('makers.defaultAnime'))
  const [gender, setGender] = useState('girl')
  const [body, setBody] = useState('slim')
  const [height, setHeight] = useState(1.62)
  const [skin, setSkin] = useState('#F3CBA4')
  const [eyeColor, setEyeColor] = useState('#3B6FC4')
  const [hairStyle, setHairStyle] = useState('long')
  const [hairColor, setHairColor] = useState('#282945')
  const [outfit, setOutfit] = useState('school')
  const [top, setTop] = useState('')
  const [bottom, setBottom] = useState('')
  const [faceSource, setFaceSource] = useState('program')
  const [faceImage, setFaceImage] = useState('')
  const [faceStyle, setFaceStyle] = useState('anime')
  const [faceShape, setFaceShape] = useState('soft')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [made, setMade] = useState<string | null>(null)

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await makeAnime({
        workspace, name: name.trim() || t('makers.defaultAnime'), gender, body, height, skin, eyeColor, hairStyle, hairColor, outfit,
        outfitColors: { ...(top ? { top } : {}), ...(bottom ? { bottom } : {}) },
        faceSource, faceStyle, faceShape, ...(faceSource === 'qwen' && faceImage.trim() ? { faceImage: faceImage.trim() } : {}),
      })
      if (mediaFilter !== 'model3d') setMediaFilter('model3d')
      await maybeRefreshGallery({ message: t('makers.animeReady'), force: true })
      setSelectedOutput(0)
      setMade(`${result.rigged_file} · cara ${result.kit_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('makers.animeFailed'))
    } finally {
      setBusy(false)
    }
  }

  const select = (label: string, value: string, choices: string[], set: (next: string) => void) => (
    <label className="text-[10px] text-text-muted">{label}
      <select className={FIELD} value={value} onChange={event => set(event.target.value)}>
        {choices.map(item => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>
  )
  const color = (label: string, value: string, set: (next: string) => void) => (
    <label className="text-[10px] text-text-muted flex items-center justify-between gap-2">{label}
      <input type="color" value={value || '#888888'} onChange={event => set(event.target.value.toUpperCase())} />
    </label>
  )
  const blocked = busy || !workspace
  return (
    <section className="rounded-lg border border-border p-3 flex flex-col gap-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{t('makers.animeTitle')}</h3>
      <label className="text-[10px] text-text-muted">{t('makers.name')}
        <input className={FIELD} value={name} maxLength={64} onChange={event => setName(event.target.value)} />
      </label>
      {select(t('makers.gender'), gender, GENDERS, setGender)}
      {select(t('makers.body'), body, BODIES, setBody)}
      <label className="text-[10px] text-text-muted">{t('makers.height', { value: height.toFixed(2) })}
        <input type="range" min={1.2} max={2.2} step={0.01} value={height} onChange={event => setHeight(Number(event.target.value))} />
      </label>
      {select(t('makers.hair'), hairStyle, HAIR, setHairStyle)}
      {color(t('makers.hairColour'), hairColor, setHairColor)}
      {color(t('makers.skin'), skin, setSkin)}
      {color(t('makers.eyes'), eyeColor, setEyeColor)}
      {select(t('makers.outfit'), outfit, OUTFITS, setOutfit)}
      {select(t('makers.faceStyle'), faceStyle, FACE_STYLES, setFaceStyle)}
      {select(t('makers.faceShape'), faceShape, FACE_SHAPES, setFaceShape)}
      {select(t('makers.faceSource'), faceSource, FACE_SOURCES, setFaceSource)}
      {faceSource === 'qwen' && <label className="text-[10px] text-text-muted">{t('makers.baldFace')}
        <input className={FIELD} value={faceImage} placeholder={t('makers.baldPlaceholder')} onChange={event => setFaceImage(event.target.value)} />
      </label>}
      {color(t('makers.top'), top, setTop)}
      {color(t('makers.bottom'), bottom, setBottom)}
      <button type="button" disabled={blocked} title={controlReason(blocked, 'disabled.actionInProgress')} onClick={() => void create()} className={`w-full px-4 py-2 rounded-lg text-xs font-medium ${busy ? 'bg-bg-tertiary text-text-muted' : 'bg-cta text-white'}`}>
        {busy ? '…' : t('makers.create')}
      </button>
      {error && <p className="text-[10px] text-red-300">{error}</p>}
      {made && <p className="text-[10px] text-text-secondary">{made}</p>}
    </section>
  )
}
