import { useMemo, useRef, useState } from 'react'
import { Box, FileJson, Image as ImageIcon, Loader2, Play, Sparkles, Square, Upload, Video, X } from 'lucide-react'
import { fetchOutputMetadata, generateLlmText, getFileUrl, getOutputThumbnailUrl, uploadImage, type ApiOutput } from '../../api/client'
import { useStore } from '../../stores/useStore'
import {
  EXAMPLE_SAUCER_CRUISE_RECIPE,
  SCENE_RECIPE_JSON_SCHEMA,
  buildRecipeSystemPrompt,
  compileRecipeShot,
  constrainManualRecipeToInventory,
  listRecipeShots,
  parseSceneRecipeText,
  RECIPE_RIG_ANIMATIONS,
  RECIPE_RIG_PROFILES,
  withResolvedSources,
  type RecipeAssetKind,
  type RecipeRigAnimation,
  type RecipeRigProfile,
  type SceneRecipe,
  type SceneRecipeShot,
} from '../../lib/sceneRecipe'
import { resolveRecipeAssets } from '../../lib/sceneRecipeAssets'
import { characterKitRecipeInventory, type CharacterKitLibrary } from '../../lib/characterKit'
import type { Scene } from '../../types'

type LoadedAsset = {
  key: string
  name: string
  kind: RecipeAssetKind
  source: string
  previewUrl: string
  description?: string
  rig_profile?: RecipeRigProfile
  animations?: RecipeRigAnimation[]
  seamlessHorizontal?: boolean
}

type PickerKind = 'image' | 'model3d'

const INTENT_EXAMPLES = [
  {
    label: 'Character entrance',
    text: 'Create a small armored explorer who walks into a misty forest and stops before a glowing stone door. Vertical, 8 seconds, slow camera push-in.',
  },
  {
    label: 'Vehicle fly-by',
    text: 'A silver saucer rises from behind a snowy ridge, pauses, then crosses left to right. Wide cinematic landscape, 8 seconds, gentle side camera.',
  },
  {
    label: 'Product turntable',
    text: 'A premium red sneaker rotates slowly at the center on a clean warm studio background. Fixed camera, 6 seconds, product reveal.',
  },
] as const

function assetPlanLabel(asset: SceneRecipe['assets'][number]): string {
  const type = asset.kind === 'model3d' ? '3D model' : asset.kind === 'video' ? 'moving plate' : 'still plate'
  return asset.source ? `Use ${type}: ${asset.source}` : `Generate ${type}: ${asset.prompt || asset.id}`
}

function shotPlanLabel(shot: SceneRecipeShot): string {
  if (shot.template) return `${shot.template} · ${Object.values(shot.slots ?? {}).join(' · ') || 'template slots'}`
  const layers = shot.layers ?? []
  const camera = layers.find(layer => layer.type === 'camera')?.cameraPreset || 'camera-locked'
  const action = layers
    .filter(layer => layer.type === 'model3d' || layer.type === 'image' || layer.type === 'video')
    .map(layer => layer.motion || layer.asset || layer.id)
    .join(' · ')
  return `${camera}${action ? ` · ${action}` : ''}`
}

function previewForOutput(item: ApiOutput): string {
  if (item.thumbnail_url) return item.thumbnail_url
  if (item.type === 'image') return item.url
  if (item.type === 'model3d') return getOutputThumbnailUrl(item.name)
  return ''
}

function kindForOutput(item: ApiOutput): RecipeAssetKind {
  if (item.type === 'model3d') return 'model3d'
  if (item.type === 'video') return 'video'
  return 'image'
}

function describeOutputParams(params: Record<string, unknown> | null): string | undefined {
  if (!params) return undefined
  const candidates = [params.prompt, params._tts_original_prompt, params.description, params.source_prompt]
  const prompt = candidates.find(value => typeof value === 'string' && value.trim())
  const animations = Array.isArray(params.animations)
    ? params.animations.filter(value => typeof value === 'string').slice(0, 16)
    : []
  const parts = [
    typeof prompt === 'string' ? prompt.replace(/\s+/g, ' ').trim().slice(0, 700) : '',
    animations.length ? `Embedded skeletal clips: ${animations.join(', ')}.` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' ') : undefined
}

function AssetThumb({
  name,
  kind,
  previewUrl,
  selected,
  onClick,
  onRemove,
  disabled,
}: {
  name: string
  kind: RecipeAssetKind
  previewUrl: string
  selected?: boolean
  onClick?: () => void
  onRemove?: () => void
  disabled?: boolean
}) {
  const [broken, setBroken] = useState(false)
  const showImage = Boolean(previewUrl) && !broken
  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        title={name}
        className={`relative aspect-square w-full overflow-hidden rounded-lg border text-left disabled:opacity-40 ${
          selected ? 'border-cyan-300 ring-2 ring-cyan-300/70' : 'border-border hover:border-cyan-400/60'
        }`}
      >
        {showImage ? (
          <img src={previewUrl} alt="" className="h-full w-full object-cover bg-bg-active" onError={() => setBroken(true)} />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 bg-bg-active text-text-muted">
            {kind === 'model3d' ? <Box size={18} /> : kind === 'video' ? <Video size={18} /> : <ImageIcon size={18} />}
          </div>
        )}
        <span className="absolute inset-x-0 bottom-0 truncate bg-black/70 px-1 py-0.5 text-[8px] text-white">{name}</span>
        <span className="absolute left-1 top-1 rounded bg-black/65 px-1 text-[7px] uppercase tracking-wide text-cyan-100">
          {kind === 'model3d' ? 'GLB' : kind === 'video' ? 'Video' : 'Image'}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          disabled={disabled}
          onClick={event => { event.stopPropagation(); onRemove() }}
          className="absolute -right-1 -top-1 z-10 rounded-full border border-border bg-black/80 p-0.5 text-red-200 hover:bg-red-600"
          aria-label={`Remove ${name}`}
        >
          <X size={10} />
        </button>
      )}
    </div>
  )
}

export function SceneRecipePanel({
  disabled,
  outputs,
  characterKits,
  onApply,
}: {
  disabled?: boolean
  outputs: ApiOutput[]
  characterKits?: CharacterKitLibrary
  onApply: (recipe: SceneRecipe, scene: Scene, status: (message: string) => void, prompt: string) => Promise<void>
}) {
  const workspace = useStore(s => s.activeWorkspace)
  const loadOutputs = useStore(s => s.loadOutputs)
  // A natural-language request should work without first understanding the
  // asset picker. Manual remains available for deterministic compositions.
  const [mode, setMode] = useState<'manual' | 'auto'>('auto')
  const [intent, setIntent] = useState('Same saucer: first it rises behind the ridge, then it cruises left to right.')
  const [recipeText, setRecipeText] = useState(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE, null, 2))
  const [selected, setSelected] = useState<LoadedAsset[]>([])
  const [picker, setPicker] = useState<PickerKind | null>(null)
  const [busy, setBusy] = useState<'write' | 'run' | 'upload' | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [shots, setShots] = useState<SceneRecipeShot[]>([])
  const [plannedRecipe, setPlannedRecipe] = useState<SceneRecipe | null>(null)
  const [activeShot, setActiveShot] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const recipeRef = useRef<SceneRecipe | null>(null)
  const resolvedRef = useRef<Record<string, string>>({})
  const imageInputRef = useRef<HTMLInputElement>(null)
  const modelInputRef = useRef<HTMLInputElement>(null)

  const gallery = useMemo(() => {
    const images = outputs.filter(item => item.type === 'image' || item.type === 'video')
    const models = outputs.filter(item => item.type === 'model3d' && /\.glb$/i.test(item.name))
    return { images, models }
  }, [outputs])
  const pickerItems = picker === 'model3d' ? gallery.models : picker === 'image' ? gallery.images : []

  const applyShot = async (recipe: SceneRecipe, shot: SceneRecipeShot, resolved: Record<string, string>) => {
    const scene = compileRecipeShot(recipe, shot, resolved, filename => getFileUrl(filename, workspace))
    await onApply({ ...recipe, record: false, save: false }, scene, setStatus, intent.trim())
  }

  const addOutput = async (item: ApiOutput) => {
    const kind = kindForOutput(item)
    setSelected(current => current.some(asset => asset.source === item.name) ? current : [
      ...current,
      { key: item.name, name: item.name, kind, source: item.name, previewUrl: previewForOutput(item) },
    ])
    try {
      const metadata = await fetchOutputMetadata(item.name, workspace)
      const description = describeOutputParams(metadata.params)
      const rawProfile = typeof metadata.params?.rig_profile === 'string' ? metadata.params.rig_profile : ''
      const rigProfile = RECIPE_RIG_PROFILES.find(profile => profile === rawProfile)
      const animations = Array.isArray(metadata.params?.animations)
        ? metadata.params.animations.filter((animation): animation is RecipeRigAnimation => typeof animation === 'string' && RECIPE_RIG_ANIMATIONS.includes(animation as RecipeRigAnimation))
        : []
      const seamlessHorizontal = metadata.params?.seamlessHorizontal === true || metadata.params?.seamless_horizontal === true
      if (!description && !animations.length && !seamlessHorizontal) return
      setSelected(current => current.map(asset => asset.source === item.name ? {
        ...asset,
        description,
        rig_profile: rigProfile,
        animations: animations.length ? animations : undefined,
        seamlessHorizontal: seamlessHorizontal || undefined,
      } : asset))
    } catch {
      // Imported and legacy outputs may not have a readable sidecar. The exact
      // source and filename remain enough for manual composition.
    }
  }

  const importFiles = async (files: File[], kind: PickerKind) => {
    if (!files.length) return
    setBusy('upload')
    setError(null)
    try {
      const next: LoadedAsset[] = []
      for (const file of files) {
        const uploaded = await uploadImage(file)
        const resolvedKind: RecipeAssetKind = kind === 'model3d' ? 'model3d' : file.type.startsWith('video/') ? 'video' : 'image'
        next.push({
          key: uploaded.filename,
          name: uploaded.filename,
          kind: resolvedKind,
          source: uploaded.filename,
          previewUrl: resolvedKind === 'model3d' ? getOutputThumbnailUrl(uploaded.filename) : uploaded.url,
        })
      }
      setSelected(current => {
        const seen = new Set(current.map(asset => asset.source))
        return [...current, ...next.filter(asset => !seen.has(asset.source))]
      })
      await loadOutputs()
      setStatus(`Added ${next.length} file${next.length === 1 ? '' : 's'} from disk.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not upload the file. Is Lab running?')
    } finally {
      setBusy(null)
    }
  }

  const writeRecipe = async () => {
    if (!intent.trim()) return
    setBusy('write')
    setError(null)
    setStatus('Interpreting the request as shots, assets and camera moves…')
    try {
      const loaded = selected.map(item => ({
        name: item.name,
        kind: item.kind,
        source: item.source,
        description: item.description,
        rig_profile: item.rig_profile,
        animations: item.animations,
        seamlessHorizontal: item.seamlessHorizontal,
      }))
      const kitInventory = characterKits ? characterKitRecipeInventory(characterKits) : []
      const fullInventory = [...loaded, ...kitInventory.filter(item => !loaded.some(selectedItem => selectedItem.source === item.source))]
      const systemPrompt = buildRecipeSystemPrompt({ mode, inventory: fullInventory })
      let text = await generateLlmText({
        prompt: intent.trim(),
        system_prompt: systemPrompt,
        max_new_tokens: 4000,
        temperature: 0.15,
        top_p: 0.85,
        frequency_penalty: 0.1,
        json_schema: SCENE_RECIPE_JSON_SCHEMA,
      })
      let recipe: SceneRecipe | null = null
      for (let attempt = 0; attempt < 3 && !recipe; attempt += 1) {
        try {
          recipe = parseSceneRecipeText(text)
        } catch (validationError) {
          if (attempt >= 2) throw validationError
          const validationMessage = validationError instanceof Error ? validationError.message : String(validationError)
          setStatus(`Repairing the LLM recipe (${attempt + 1}/2): ${validationMessage}`)
          text = await generateLlmText({
            prompt: `Repair your previous recipe without changing the user's intent. Preserve every valid requested subject and action, fix the validation error, and return one complete replacement JSON object.\n\nUSER INTENT:\n${intent.trim()}\n\nVALIDATION ERROR:\n${validationMessage}\n\nPREVIOUS RECIPE:\n${text.slice(0, 16_000)}`,
            system_prompt: systemPrompt,
            max_new_tokens: 4000,
            temperature: 0.05,
            top_p: 0.8,
            json_schema: SCENE_RECIPE_JSON_SCHEMA,
          })
        }
      }
      if (!recipe) throw new Error('The LLM did not produce a valid recipe after two repairs.')
      if (mode === 'manual') {
        recipe = constrainManualRecipeToInventory(recipe, fullInventory)
      }
      setRecipeText(JSON.stringify(recipe, null, 2))
      setPlannedRecipe(recipe)
      setShots(listRecipeShots(recipe))
      setActiveShot(0)
      setStatus(`Recipe ready: ${recipe.name} · ${listRecipeShots(recipe).length} shot(s). Preview and edit before recording.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(null)
    }
  }

  const runRecipe = async () => {
    abortRef.current?.abort()
    const abort = new AbortController()
    abortRef.current = abort
    setBusy('run')
    setError(null)
    try {
      const recipe = parseSceneRecipeText(recipeText)
      setStatus(mode === 'manual' ? 'Using loaded assets and audio…' : 'Resolving assets and audio (generate only what is missing)…')
      const resolved = await resolveRecipeAssets(recipe, {
        workspace,
        onStatus: setStatus,
        signal: abort.signal,
        generateMissing: mode === 'auto',
      })
      const stored = withResolvedSources(recipe, resolved)
      setRecipeText(JSON.stringify(stored, null, 2))
      recipeRef.current = stored
      resolvedRef.current = resolved
      const nextShots = listRecipeShots(stored)
      setShots(nextShots)
      setActiveShot(0)
      await applyShot(stored, nextShots[0], resolved)
      setStatus(`Mounted shot “${nextShots[0].name}”. Tweak it in the inspector, then Record.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      if (abortRef.current === abort) abortRef.current = null
      setBusy(null)
    }
  }

  const mountShot = async (index: number) => {
    const recipe = recipeRef.current || parseSceneRecipeText(recipeText)
    const resolved = Object.keys(resolvedRef.current).length
      ? resolvedRef.current
      : Object.fromEntries(recipe.assets.filter(asset => asset.source).map(asset => [asset.id, asset.source as string]))
    const nextShots = listRecipeShots(recipe)
    const shot = nextShots[index]
    if (!shot) return
    setActiveShot(index)
    setBusy('run')
    setError(null)
    try {
      await applyShot(recipe, shot, resolved)
      setStatus(`Mounted shot “${shot.name}”. Edit freely, then Record.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(null)
    }
  }

  const locked = Boolean(busy) || disabled

  return (
    <div className="space-y-2 rounded border border-cyan-400/30 bg-cyan-400/[.04] p-2">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-cyan-200">
        <Sparkles size={12} /> Recipe runner
      </div>
      <div className="grid grid-cols-2 gap-1">
        {(['manual', 'auto'] as const).map(value => (
          <button
            key={value}
            type="button"
            disabled={locked}
            onClick={() => setMode(value)}
            className={`rounded border px-2 py-1 text-[10px] ${
              mode === value ? 'border-cyan-300 bg-cyan-400/15 text-cyan-100' : 'border-border text-text-muted'
            }`}
          >
            {value === 'manual' ? 'Manual · loaded assets' : 'Auto · generate missing'}
          </button>
        ))}
      </div>
      <p className="text-[8px] text-text-muted">
        {mode === 'manual'
          ? 'Add plates and GLBs with previews, then ask the LLM to compose. Edit the scene, then Record.'
          : 'Describe the scene normally. HocusPocus plans reusable 3D subjects, plates, camera and effects; review the plan before generation.'}
      </p>

      <details className="rounded border border-border bg-bg-primary/45 px-2 py-1.5 text-[9px] text-text-muted">
        <summary className="cursor-pointer font-medium text-text-secondary">How to describe a scene</summary>
        <p className="mt-1 leading-relaxed">Mention subjects that must keep their identity, actions in order, the setting, and optionally camera, duration or format. Moving characters, vehicles and objects become separate reusable 3D assets; a fixed environment becomes one plate; fog, snow and rain become effects.</p>
      </details>

      {mode === 'manual' && (
        <div className="space-y-2">
          <div className="flex gap-1">
            <button
              type="button"
              disabled={locked}
              onClick={() => setPicker(current => current === 'image' ? null : 'image')}
              className={`flex flex-1 items-center justify-center gap-1 rounded border px-2 py-1.5 text-[10px] ${
                picker === 'image' ? 'border-cyan-300 bg-cyan-400/15 text-cyan-100' : 'border-border text-text-secondary'
              }`}
            >
              <ImageIcon size={12} /> Images
            </button>
            <button
              type="button"
              disabled={locked}
              onClick={() => setPicker(current => current === 'model3d' ? null : 'model3d')}
              className={`flex flex-1 items-center justify-center gap-1 rounded border px-2 py-1.5 text-[10px] ${
                picker === 'model3d' ? 'border-cyan-300 bg-cyan-400/15 text-cyan-100' : 'border-border text-text-secondary'
              }`}
            >
              <Box size={12} /> 3D models
            </button>
          </div>

          {selected.length > 0 && (
            <div>
              <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">Selected · {selected.length}</div>
              <div className="grid grid-cols-3 gap-1.5">
                {selected.map(asset => (
                  <AssetThumb
                    key={asset.key}
                    name={asset.name}
                    kind={asset.kind}
                    previewUrl={asset.previewUrl}
                    selected
                    disabled={locked}
                    onRemove={() => setSelected(current => current.filter(item => item.key !== asset.key))}
                  />
                ))}
              </div>
            </div>
          )}

          {picker && (
            <div className="rounded border border-border bg-bg-primary p-2">
              <div className="mb-1.5 flex items-center justify-between gap-1">
                <span className="text-[10px] text-text-muted">
                  {picker === 'model3d' ? 'GLBs from HocusPocus' : 'Images & videos from HocusPocus'}
                </span>
                <button type="button" onClick={() => setPicker(null)} className="text-text-muted hover:text-text-primary"><X size={12} /></button>
              </div>
              <button
                type="button"
                disabled={locked}
                onClick={() => (picker === 'model3d' ? modelInputRef : imageInputRef).current?.click()}
                className="mb-2 flex w-full items-center justify-center gap-1 rounded border border-dashed border-cyan-400/40 py-1.5 text-[10px] text-cyan-200 hover:bg-cyan-400/10 disabled:opacity-40"
              >
                {busy === 'upload' ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                {picker === 'model3d' ? 'Import GLB from disk' : 'Import image from disk'}
              </button>
              {pickerItems.length ? (
                <div className="grid max-h-52 grid-cols-3 gap-1.5 overflow-y-auto">
                  {pickerItems.map(item => (
                    <AssetThumb
                      key={item.name}
                      name={item.name}
                      kind={kindForOutput(item)}
                      previewUrl={previewForOutput(item)}
                      selected={selected.some(asset => asset.source === item.name)}
                      disabled={locked}
                      onClick={() => void addOutput(item)}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-[9px] text-text-muted">
                  {picker === 'model3d' ? 'No GLBs in Outputs yet. Import one from disk.' : 'No images in Outputs yet. Import one from disk.'}
                </p>
              )}
            </div>
          )}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*,video/*"
            multiple
            className="hidden"
            onChange={event => {
              void importFiles(Array.from(event.target.files || []), 'image')
              event.currentTarget.value = ''
            }}
          />
          <input
            ref={modelInputRef}
            type="file"
            accept=".glb,model/gltf-binary"
            multiple
            className="hidden"
            onChange={event => {
              void importFiles(Array.from(event.target.files || []), 'model3d')
              event.currentTarget.value = ''
            }}
          />
        </div>
      )}

      <label className="block text-[10px] text-text-muted">
        Describe the scene
        <textarea
          rows={3}
          value={intent}
          disabled={locked}
          onChange={event => setIntent(event.target.value)}
          className="mt-1 w-full resize-y rounded border border-border bg-bg-primary px-2 py-1.5 text-[10px] text-text-primary"
        />
      </label>
      <div className="flex flex-wrap gap-1" aria-label="Scene request examples">
        {INTENT_EXAMPLES.map(example => (
          <button
            key={example.label}
            type="button"
            disabled={locked}
            onClick={() => setIntent(example.text)}
            className="rounded border border-border px-1.5 py-1 text-[8px] text-text-muted hover:border-cyan-400/60 hover:text-cyan-100 disabled:opacity-40"
          >
            {example.label}
          </button>
        ))}
      </div>
      <div className="flex gap-1.5">
        <button
          type="button"
          disabled={locked || !intent.trim() || (mode === 'manual' && !selected.length)}
          onClick={() => void writeRecipe()}
          className="flex flex-1 items-center justify-center gap-1 rounded border border-border bg-bg-primary py-1.5 text-[10px] disabled:opacity-40"
        >
          {busy === 'write' ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
          Plan scene
        </button>
        <button
          type="button"
          disabled={locked}
          onClick={() => {
            setRecipeText(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE, null, 2))
            setShots(listRecipeShots(EXAMPLE_SAUCER_CRUISE_RECIPE))
            setPlannedRecipe(EXAMPLE_SAUCER_CRUISE_RECIPE)
          }}
          className="flex items-center justify-center gap-1 rounded border border-border bg-bg-primary px-2 py-1.5 text-[10px] disabled:opacity-40"
        >
          <FileJson size={11} /> Example
        </button>
      </div>
      {plannedRecipe && (
        <section aria-label="Scene plan" className="space-y-1.5 rounded border border-cyan-400/30 bg-cyan-400/[.07] p-2">
          <div className="text-[9px] font-medium uppercase tracking-wider text-cyan-100">Review plan · {plannedRecipe.shots?.length || 1} shot{(plannedRecipe.shots?.length || 1) === 1 ? '' : 's'}</div>
          <div className="space-y-1">
            {plannedRecipe.assets.map(asset => (
              <p key={asset.id} className="text-[8px] leading-relaxed text-text-secondary"><span className="font-medium text-cyan-100">{asset.id}</span> — {assetPlanLabel(asset)}</p>
            ))}
          </div>
          <div className="space-y-1 border-t border-cyan-400/15 pt-1">
            {(plannedRecipe.shots?.length ? plannedRecipe.shots : [{ name: 'scene', duration: plannedRecipe.scene.duration, layers: plannedRecipe.scene.layers }]).map((shot, index) => (
              <p key={`${shot.name}-${index}`} className="text-[8px] text-text-muted">{index + 1}. {shot.name} · {shot.duration || plannedRecipe.scene.duration || 5}s · {shotPlanLabel(shot)}</p>
            ))}
          </div>
        </section>
      )}
      <details className="rounded border border-border bg-bg-primary/30 px-2 py-1.5">
        <summary className="cursor-pointer text-[9px] text-text-muted">Advanced: edit recipe JSON</summary>
        <textarea
          aria-label="Recipe JSON"
          rows={8}
          value={recipeText}
          disabled={locked}
          onChange={event => { setRecipeText(event.target.value); setPlannedRecipe(null) }}
          spellCheck={false}
          className="mt-1 w-full resize-y rounded border border-border bg-bg-primary px-2 py-1.5 font-mono text-[9px] text-text-primary"
        />
      </details>
      <div className="flex gap-1.5">
        <button
          type="button"
          disabled={locked}
          onClick={() => void runRecipe()}
          className="flex flex-1 items-center justify-center gap-1 rounded bg-cyan-600 py-1.5 text-[10px] text-white disabled:opacity-40"
        >
          {busy === 'run' ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
          {busy === 'run' ? 'Working…' : mode === 'manual' ? 'Compose' : 'Generate + compose'}
        </button>
        {busy && busy !== 'upload' && (
          <button
            type="button"
            onClick={() => abortRef.current?.abort()}
            className="flex items-center justify-center gap-1 rounded border border-red-400/50 px-2 py-1.5 text-[10px] text-red-200"
          >
            <Square size={10} /> Cancel
          </button>
        )}
      </div>
      {shots.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {shots.map((shot, index) => (
            <button
              key={`${shot.name}-${index}`}
              type="button"
              disabled={locked}
              onClick={() => void mountShot(index)}
              className={`rounded border px-1.5 py-1 text-[9px] ${
                index === activeShot ? 'border-cyan-300 bg-cyan-400/15 text-cyan-100' : 'border-border text-text-muted'
              }`}
            >
              {shot.name}
            </button>
          ))}
        </div>
      )}
      {status && <p className="text-[9px] text-cyan-200">{status}</p>}
      {error && <p className="text-[9px] text-red-300">{error}</p>}
    </div>
  )
}
