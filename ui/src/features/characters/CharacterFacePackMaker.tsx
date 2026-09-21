import { useMemo, useState } from 'react'
import { EXPRESSIONS, VISEMES, type Expression, type Viseme } from '../scene3d/speech/types'
import {
  EXPRESSION_EYES,
  FACE_PLANE_REST_PROMPT,
  VISEME_ALIASES,
  VISEME_MOUTHS,
  expressionPrompt,
  fillFacePrompt,
  parseFacePackStillName,
  visemePrompt,
} from '../scene3d/speech/facePackPrompts'
import { composeFacePack } from '../scene3d/speech/facePackAssemble'
import { useUiTranslation } from '../../i18n'

const field = 'mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary'
const button = 'rounded border border-border px-3 py-2 text-xs text-text-primary disabled:opacity-40'

export function CharacterFacePackMaker() {
  const { t } = useUiTranslation('characters')
  const [skin, setSkin] = useState('cream felt fabric')
  const [stills, setStills] = useState<Record<string, string>>({})
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [status, setStatus] = useState('')
  const restPrompt = useMemo(() => fillFacePrompt(FACE_PLANE_REST_PROMPT, skin), [skin])

  const loadFiles = (list: FileList | null) => {
    if (!list) return
    for (const file of Array.from(list)) {
      const parsed = parseFacePackStillName(file.name)
      if (!parsed) {
        setStatus(t('facePackMaker.unknownFile', { name: file.name }))
        continue
      }
      const key = parsed.kind === 'rest' ? 'rest' : parsed.id
      const url = URL.createObjectURL(file)
      setStills(current => {
        if (current[key]) URL.revokeObjectURL(current[key])
        return { ...current, [key]: url }
      })
      setStatus(t('facePackMaker.loaded', { name: key }))
    }
  }

  const copy = (text: string) => { void navigator.clipboard.writeText(text) }

  const build = async () => {
    if (!stills.rest) {
      setStatus(t('facePackMaker.needRest'))
      return
    }
    const load = (src: string) => new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image()
      image.onload = () => resolve(image)
      image.onerror = () => reject(new Error(src))
      image.src = src
    })
    try {
      const rest = await load(stills.rest)
      const visemes: Partial<Record<Viseme, HTMLImageElement>> = {}
      const expressions: Partial<Record<Expression, HTMLImageElement>> = {}
      for (const viseme of VISEMES) {
        if (viseme === 'rest' || !stills[viseme]) continue
        visemes[viseme] = await load(stills[viseme])
      }
      for (const expression of EXPRESSIONS) {
        if (expression === 'neutral' || !stills[expression]) continue
        expressions[expression] = await load(stills[expression])
      }
      const canvas = composeFacePack({ rest, visemes, expressions })
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      const url = canvas.toDataURL('image/png')
      setPreviewUrl(url)
      setStatus(t('facePackMaker.ready'))
    } catch {
      setStatus(t('facePackMaker.buildFailed'))
    }
  }

  const slot = (key: string) => (
    <label key={key} className="rounded border border-dashed border-border p-2 text-[10px] text-text-secondary">
      <span className="block font-medium text-text-primary">{key}</span>
      {stills[key]
        ? <img src={stills[key]} alt="" className="mt-1 aspect-square w-full rounded object-cover" />
        : <span className="mt-1 block text-text-muted">{t('facePackMaker.empty')}</span>}
    </label>
  )

  return (
    <section data-testid="character-face-pack-maker" aria-label={t('facePackMaker.title')} className="mx-auto mb-4 max-w-5xl space-y-3 rounded-lg border border-violet-400/30 bg-bg-secondary p-3">
      <h3 className="text-sm font-semibold text-text-primary">{t('facePackMaker.title')}</h3>
      <p className="text-xs leading-5 text-text-secondary">{t('facePackMaker.intro')}</p>
      <label className="block text-xs text-text-secondary">{t('facePackMaker.skin')}
        <input value={skin} onChange={event => setSkin(event.target.value)} className={field} />
      </label>
      <label className="block text-xs text-text-secondary">{t('facePackMaker.restPrompt')}
        <textarea readOnly value={restPrompt} rows={4} className={`${field} font-mono`} />
      </label>
      <button type="button" className={button} onClick={() => copy(restPrompt)}>{t('facePackMaker.copyRest')}</button>
      <details className="rounded border border-border p-2">
        <summary className="cursor-pointer text-xs text-text-primary">{t('facePackMaker.editPrompts')}</summary>
        <div className="mt-2 space-y-2">
          {VISEMES.filter(id => id !== 'rest').map(id => {
            const text = visemePrompt(id, skin)
            return <div key={id}>
              <p className="text-[10px] text-text-muted">{id}{VISEME_ALIASES[id] ? ` → ${VISEME_ALIASES[id]}` : ''} · {VISEME_MOUTHS[id].slice(22)}</p>
              <button type="button" className={button} onClick={() => copy(text)}>{t('facePackMaker.copyNamed', { name: id })}</button>
            </div>
          })}
          {EXPRESSIONS.filter(id => id !== 'neutral').map(id => {
            const text = expressionPrompt(id, skin)
            return <div key={id}>
              <p className="text-[10px] text-text-muted">{id} · {EXPRESSION_EYES[id].slice(40)}</p>
              <button type="button" className={button} onClick={() => copy(text)}>{t('facePackMaker.copyNamed', { name: id })}</button>
            </div>
          })}
        </div>
      </details>
      <label className="block text-xs text-text-secondary">{t('facePackMaker.stills')}
        <input type="file" accept="image/*" multiple className="mt-1 block max-w-full" onChange={event => loadFiles(event.target.files)} />
      </label>
      <p className="text-[10px] text-text-muted">{t('facePackMaker.naming')}</p>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {slot('rest')}
        {VISEMES.filter(id => id !== 'rest').map(slot)}
        {EXPRESSIONS.filter(id => id !== 'neutral').map(slot)}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} disabled={!stills.rest} onClick={() => void build()}>{t('facePackMaker.build')}</button>
        {previewUrl && <a className={button} href={previewUrl} download="pack.png">{t('facePackMaker.download')}</a>}
      </div>
      {status && <p role="status" className="text-xs text-emerald-200">{status}</p>}
      {previewUrl && <img src={previewUrl} alt={t('facePackMaker.previewAlt')} className="w-full rounded border border-border bg-bg-primary" />}
    </section>
  )
}
