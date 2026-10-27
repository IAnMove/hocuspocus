import { useState } from 'react'
import { makeAnime } from '../../api/blobBody'
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
  const workspace = useStore(state => state.activeWorkspace)
  const mediaFilter = useStore(state => state.mediaFilter)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const maybeRefreshGallery = useStore(state => state.maybeRefreshGallery)
  const setSelectedOutput = useStore(state => state.setSelectedOutput)
  const [name, setName] = useState('Anime')
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
        workspace, name: name.trim() || 'Anime', gender, body, height, skin, eyeColor, hairStyle, hairColor, outfit,
        outfitColors: { ...(top ? { top } : {}), ...(bottom ? { bottom } : {}) },
        faceSource, faceStyle, faceShape, ...(faceSource === 'qwen' && faceImage.trim() ? { faceImage: faceImage.trim() } : {}),
      })
      if (mediaFilter !== 'model3d') setMediaFilter('model3d')
      await maybeRefreshGallery({ message: 'Personaje anime listo', force: true })
      setSelectedOutput(0)
      setMade(`${result.rigged_file} · cara ${result.kit_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not build the anime character')
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
  return (
    <section className="rounded-lg border border-border p-3 flex flex-col gap-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Personaje anime 3D</h3>
      <label className="text-[10px] text-text-muted">Name
        <input className={FIELD} value={name} maxLength={64} onChange={event => setName(event.target.value)} />
      </label>
      {select('Gender', gender, GENDERS, setGender)}
      {select('Body', body, BODIES, setBody)}
      <label className="text-[10px] text-text-muted">Height {height.toFixed(2)} m
        <input type="range" min={1.2} max={2.2} step={0.01} value={height} onChange={event => setHeight(Number(event.target.value))} />
      </label>
      {select('Hair', hairStyle, HAIR, setHairStyle)}
      {color('Hair colour', hairColor, setHairColor)}
      {color('Skin', skin, setSkin)}
      {color('Eyes', eyeColor, setEyeColor)}
      {select('Outfit', outfit, OUTFITS, setOutfit)}
      {select('Face style', faceStyle, FACE_STYLES, setFaceStyle)}
      {select('Face shape', faceShape, FACE_SHAPES, setFaceShape)}
      {select('Face source', faceSource, FACE_SOURCES, setFaceSource)}
      {faceSource === 'qwen' && <label className="text-[10px] text-text-muted">Bald face picture (keyed, this workspace)
        <input className={FIELD} value={faceImage} placeholder="bald_face.no-background-….png" onChange={event => setFaceImage(event.target.value)} />
      </label>}
      {color('Top', top, setTop)}
      {color('Bottom', bottom, setBottom)}
      <button type="button" disabled={busy || !workspace} onClick={() => void create()} className={`w-full px-4 py-2 rounded-lg text-xs font-medium ${busy ? 'bg-bg-tertiary text-text-muted' : 'bg-cta text-white'}`}>
        {busy ? '…' : 'Crear'}
      </button>
      {error && <p className="text-[10px] text-red-300">{error}</p>}
      {made && <p className="text-[10px] text-text-secondary">{made}</p>}
    </section>
  )
}
