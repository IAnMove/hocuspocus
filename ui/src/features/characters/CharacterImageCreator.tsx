import { useEffect, useRef, useState } from 'react'
import { Loader2, Save, WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { cancelJob } from '../../api/client'
import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import { generateImageAsset } from '../../lib/imageGeneration'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../../lib/characterKit'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import { randomUuid } from '../../lib/uuid'
import { characterStyle, characterStyleLabel, characterStyles, characterStyleSummary } from '../../lib/characterStyles'
import { CharacterStyleCreator } from './CharacterStyleCreator'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

/** Generate an identity first; saving it makes it available to Lips Creator. */
export function CharacterImageCreator({ workspace, disabled, onUseReference }: {
  workspace: string; disabled?: boolean
  onUseReference: (asset: CharacterKitAsset, description: string, signal: AbortSignal) => Promise<void>
}) {
  const { t, i18n } = useUiTranslation('characters')
  const models = useStore(state => state.models)
  const [styleId, setStyleId] = useState('')
  const style = characterStyle(styleId)
  const imageModels = characterImageModels(models, false)
  const [model, setModel] = useState(''), [name, setName] = useState(''), [description, setDescription] = useState('')
  const [draft, setDraft] = useState<CharacterKit>(), [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null), job = useRef<string | null>(null)
  const imageModel = imageModels.some(item => item.model_type === model) ? model : preferredCharacterImageModel(imageModels, false)
  useEffect(() => () => {
    operation.current?.abort()
    if (job.current) void cancelJob(job.current).catch(() => {})
  }, [])
  const run = async (label: string, task: (signal: AbortSignal) => Promise<void>) => {
    if (operation.current || disabled) return
    const controller = new AbortController(); operation.current = controller
    setBusy(label); setError(''); setMessage('')
    try { await task(controller.signal) }
    catch (cause) { if (!controller.signal.aborted) setError((cause as Error).message) }
    finally {
      if (!controller.signal.aborted) { operation.current = null; job.current = null; setBusy('') }
    }
  }
  const stop = () => {
    operation.current?.abort(); operation.current = null
    if (job.current) void cancelJob(job.current).catch(() => {})
    job.current = null; setBusy(''); setMessage(t('imageCreator.cancelled'))
  }
  const generate = () => run('generate', async signal => {
    const prompt = `Create a single character illustration. ${description.trim()}. Clear front-facing face, relaxed expression and closed mouth, coherent anatomy, uncluttered background. Follow the described appearance and art style. One character only, no text, watermark, grid or turnaround sheet.`
    const result = await generateImageAsset('maestro', prompt, imageModel, undefined,
      'text, watermark, multiple characters, sprite sheet, grid, cropped face', {
        workspace, signal, cleanModelDefaults: true, resolution: '1024x1024', aspectRatio: '1:1', comicPanel: false,
        onJobSubmitted: id => {
          if (signal.aborted) { void cancelJob(id).catch(() => {}); return }
          job.current = id
        },
      })
    signal.throwIfAborted(); job.current = null
    const kit = createCharacterKit(name.trim()); kit.id = `character-${randomUuid()}`
    kit.base = { id: `${kit.id}-base`, name: kit.name, source: result.source, kind: 'image', reviewState: 'pending',
      alphaStatus: 'unknown', model: result.model || imageModel, prompt, workspace }
    kit.identityReference = { ...kit.base }; kit.lookNotes = description.trim()
    kit.provenance = [{ method: 'character-description-generate', source: result.source, model: kit.base.model,
      prompt, workspace, jobId: result.metadata?.jobId }]
    setDraft(kit); setSaved(false); setMessage(t('imageCreator.review'))
    void useStore.getState().loadOutputs().catch(() => {})
  })
  const save = () => run('save', async signal => {
    if (!draft?.base) return
    const library = await fetchCharacterKitLibrary(workspace); signal.throwIfAborted()
    const kit: CharacterKit = { ...draft, name: name.trim(),
      base: { ...draft.base, name: name.trim(), reviewState: 'approved' },
      identityReference: { ...draft.base, name: name.trim(), reviewState: 'approved' } }
    const result = await saveCharacterKit(workspace, library, kit); signal.throwIfAborted()
    setDraft(result.kits[kit.id]); setSaved(true); setMessage(t('imageCreator.saved'))
  })
  const blocked = Boolean(busy) || disabled
  return <section data-testid="character-image-creator" className="mx-auto mb-5 max-w-5xl space-y-4 rounded-xl border border-cyan-400/30 bg-bg-secondary p-4">
    <div><h3 className="text-base font-semibold">{t('imageCreator.title')}</h3><p className="mt-1 text-sm text-text-muted">{t(style ? 'styleCreator.hint' : 'imageCreator.hint')}</p></div>
    <label className="block max-w-md text-xs text-text-secondary">{t('styleCreator.style')}
      <select value={styleId} disabled={Boolean(busy) || disabled} onChange={event => setStyleId(event.target.value)} className={`${control} mt-1 w-full`} data-testid="character-style">
        <option value="">{t('styleCreator.free')}</option>
        {characterStyles.map(item => <option key={item.id} value={item.id}>{characterStyleLabel(item, i18n.language)}</option>)}
      </select>
      {style && <span className="mt-1 block text-text-muted">{characterStyleSummary(style, i18n.language)}</span>}
    </label>
    {style ? <>
      <label className="block max-w-md text-xs text-text-secondary">{t('lips.imageModel')}<select value={imageModel} disabled={disabled} onChange={event => setModel(event.target.value)} className={`${control} mt-1 w-full`}>
        {!imageModels.length && <option value="">{t('lips.noImageModel')}</option>}{imageModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
      </select></label>
      <CharacterStyleCreator key={style.id} workspace={workspace} style={style} model={imageModel} disabled={disabled} />
    </> : <>
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_15rem]">
      <div className="space-y-3">
        <label className="block text-xs text-text-secondary">{t('imageCreator.name')}<input value={name} maxLength={80} disabled={blocked || saved} onChange={event => setName(event.target.value)} className={`${control} mt-1 w-full`} /></label>
        <label className="block text-xs text-text-secondary">{t('imageCreator.description')}<textarea value={description} maxLength={2000} rows={3} disabled={blocked} onChange={event => setDescription(event.target.value)} placeholder={t('imageCreator.placeholder')} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-3 text-sm" /></label>
        <label className="block text-xs text-text-secondary">{t('lips.imageModel')}<select value={imageModel} disabled={blocked} onChange={event => setModel(event.target.value)} className={`${control} mt-1 w-full`}>
          {!imageModels.length && <option value="">{t('lips.noImageModel')}</option>}{imageModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
        </select></label>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={blocked || !imageModel || !name.trim() || !description.trim()} onClick={() => void generate()} className={`${control} inline-flex items-center gap-2 text-cyan-200`}>
            {busy === 'generate' ? <Loader2 size={15} className="animate-spin" /> : <WandSparkles size={15} />}{t(draft ? 'imageCreator.regenerate' : 'imageCreator.generate')}</button>
          {busy === 'generate' && <button type="button" onClick={stop} className={control}>{t('lips.cancel')}</button>}
        </div>
      </div>
      {draft?.base ? <div className="space-y-3">
        <img src={draft.base.source} alt={draft.name} className="aspect-square w-full rounded-lg border border-border object-contain" />
        <button type="button" disabled={blocked || saved || !name.trim()} onClick={() => void save()} className={`${control} inline-flex w-full items-center justify-center gap-2`}><Save size={15} />{t('imageCreator.save')}</button>
        {saved && <button type="button" disabled={blocked} onClick={() => useStore.getState().setMediaFilter('lips')} className={`${control} w-full text-cyan-200`}>{t('imageCreator.createMouths')}</button>}
        <button type="button" disabled={blocked} onClick={() => void run('reference', async signal => {
          await onUseReference(draft.base!, draft.lookNotes || description, signal); signal.throwIfAborted(); setMessage(t('imageCreator.referenceReady'))
        })} className={`${control} w-full`}>{t('imageCreator.useReference')}</button>
      </div> : <div className="flex min-h-36 items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-text-muted">{t('imageCreator.empty')}</div>}
    </div>
    {busy && <p role="status" className="text-sm text-text-muted">{t(busy === 'generate' ? 'imageCreator.generating' : 'lips.saving')}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    </>}
  </section>
}
