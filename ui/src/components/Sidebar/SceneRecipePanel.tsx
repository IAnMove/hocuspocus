import { useEffect, useMemo, useRef, useState } from 'react'
import type { TFunction } from 'i18next'
import { Box, FileJson, Image as ImageIcon, Loader2, Play, Sparkles, Square, Video, X } from 'lucide-react'
import { fetchOutputMetadata, generateLlmText, getFileUrl, getOutputThumbnailUrl, type ApiOutput } from '../../api/client'
import {
  listenForProgrammaticVideoPreparation,
  type ProgrammaticVideoPreparation,
  type ProgrammaticVideoPreparationAck,
} from '../../features/agent/programmaticVideoHandoff'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
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
import {
  effectiveSceneGenerationPolicy,
  SceneGenerationPolicyError,
  withSceneGenerationPolicy,
  type SceneGenerationPolicy,
} from '../../lib/sceneGenerationPolicy'
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

const INTENT_EXAMPLES = [
  {
    key: 'entrance' as const,
    text: 'Create a small armored explorer who walks into a misty forest and stops before a glowing stone door. Vertical, 8 seconds, slow camera push-in.',
  },
  {
    key: 'flyby' as const,
    text: 'A silver saucer rises from behind a snowy ridge, pauses, then crosses left to right. Wide cinematic landscape, 8 seconds, gentle side camera.',
  },
  {
    key: 'turntable' as const,
    text: 'A premium red sneaker rotates slowly at the center on a clean warm studio background. Fixed camera, 6 seconds, product reveal.',
  },
] as const

const DEFAULT_INTENT = 'Same saucer: first it rises behind the ridge, then it cruises left to right.'

type PendingProgrammaticPreparationAck = {
  request: ProgrammaticVideoPreparation
  selectedSources: string[]
  resolve: (ack: ProgrammaticVideoPreparationAck) => void
  reject: (error: Error) => void
}

function assetKindLabel(kind: RecipeAssetKind, t: TFunction<'scene3d'>) {
  return kind === 'model3d' ? t('recipe.typeModel') : kind === 'video' ? t('recipe.typeVideo') : t('recipe.typeStill')
}

function assetPlanLabel(asset: SceneRecipe['assets'][number], t: TFunction<'scene3d'>): string {
  const type = assetKindLabel(asset.kind, t)
  return asset.source ? t('recipe.useAsset', { type, source: asset.source }) : t('recipe.generateAsset', { type, prompt: asset.prompt || asset.id })
}

function shotPlanLabel(shot: SceneRecipeShot, t: TFunction<'scene3d'>): string {
  if (shot.template) return `${shot.template} · ${Object.values(shot.slots ?? {}).join(' · ') || t('recipe.templateSlots')}`
  const layers = shot.layers ?? []
  const camera = layers.find(layer => layer.type === 'camera')?.cameraPreset || 'camera-locked'
  const action = layers
    .filter(layer => layer.type === 'model3d' || layer.type === 'image' || layer.type === 'video')
    .map(layer => layer.motion || layer.asset || layer.id)
    .join(' · ')
  return `${camera}${action ? ` · ${action}` : ''}`
}

function callerGenerationPolicy(
  mode: 'manual' | 'auto',
  noVideoGeneration: boolean,
  trustedPolicy?: ProgrammaticVideoPreparation['generationPolicy'],
): SceneGenerationPolicy {
  const selectedPolicy = mode === 'manual' ? 'provided_only' : noVideoGeneration ? 'no_video_generation' : 'auto'
  return effectiveSceneGenerationPolicy(
    trustedPolicy,
    selectedPolicy,
  )
}

function generationPolicyInstructions(policy: SceneGenerationPolicy): string {
  if (policy === 'provided_only') {
    return `TRUSTED CALLER GENERATION POLICY: provided_only.
- Use every supplied image, video, 3D model and audio source exactly as provided.
- Never emit a prompt-only asset or audio track, and never request an image, audio, video, model or rig generation job.
- Preserve the user's requested story and shot order; change only unsupported generated resources into a clear missing-source validation failure.`
  }
  if (policy === 'no_video_generation') {
    return `TRUSTED CALLER GENERATION POLICY: no_video_generation.
- Never request or create a generated video asset. An existing supplied video source is allowed and must be copied exactly.
- Images, audio and 3D assets may still be generated when they are missing and the normal mode permits it.
- Preserve the user's requested story and shot order; do not translate or rewrite the user's intent.`
  }
  return `TRUSTED CALLER GENERATION POLICY: auto.
- Missing assets may be generated according to the normal mode rules.
- Do not weaken or override a more restrictive policy that may already be present in the recipe JSON.`
}

function recipeErrorMessage(reason: unknown, t: TFunction<'scene3d'>): string {
  if (reason instanceof SceneGenerationPolicyError) {
    if (reason.code === 'generation_forbidden') {
      return t('recipe.policyError.generationForbidden', {
        policy: reason.policy,
        assetId: reason.assetId,
        kind: reason.kind === 'audio' ? t('recipe.typeAudio') : assetKindLabel(reason.kind as RecipeAssetKind, t),
      })
    }
    return t('recipe.policyError.unknown')
  }
  return reason instanceof Error ? reason.message : String(reason)
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
  const { t } = useUiTranslation('scene3d')
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
          {kind === 'model3d' ? t('recipe.kindGlb') : kind === 'video' ? t('recipe.kindVideo') : t('recipe.kindImage')}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          disabled={disabled}
          onClick={event => { event.stopPropagation(); onRemove() }}
          className="absolute -right-1 -top-1 z-10 rounded-full border border-border bg-black/80 p-0.5 text-red-200 hover:bg-red-600"
          aria-label={t('recipe.removeAria', { name })}
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
  title?: string
  outputs: ApiOutput[]
  characterKits?: CharacterKitLibrary
  onApply: (recipe: SceneRecipe, scene: Scene, status: (message: string) => void, prompt: string) => Promise<void>
}) {
  const { t } = useUiTranslation('scene3d')
  const workspace = useStore(s => s.activeWorkspace)
  // A natural-language request should work without first understanding the
  // asset picker. Manual remains available for deterministic compositions.
  const [mode, setMode] = useState<'manual' | 'auto'>('auto')
  const [noVideoGeneration, setNoVideoGeneration] = useState(false)
  const [intent, setIntent] = useState(DEFAULT_INTENT)
  const [recipeText, setRecipeText] = useState(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE, null, 2))
  const [selected, setSelected] = useState<LoadedAsset[]>([])
  const [programmaticPreparation, setProgrammaticPreparation] = useState<ProgrammaticVideoPreparation | null>(null)

  const [busy, setBusy] = useState<'write' | 'run' | 'upload' | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [shots, setShots] = useState<SceneRecipeShot[]>([])
  const [plannedRecipe, setPlannedRecipe] = useState<SceneRecipe | null>(null)
  const [activeShot, setActiveShot] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const workspaceRef = useRef(workspace)
  const outputsRef = useRef(outputs)
  const pendingPreparationAckRef = useRef<PendingProgrammaticPreparationAck | null>(null)
  const busyRef = useRef(busy)
  const disabledRef = useRef(Boolean(disabled))
  const translationRef = useRef(t)
  workspaceRef.current = workspace
  outputsRef.current = outputs
  busyRef.current = busy
  disabledRef.current = Boolean(disabled)
  translationRef.current = t

  const gallery = useMemo(() => {
    const images = outputs.filter(item => item.type === 'image' || item.type === 'video')
    const models = outputs.filter(item => item.type === 'model3d' && /\.glb$/i.test(item.name))
    return { images, models }
  }, [outputs])


  useEffect(() => {
    const unsubscribe = listenForProgrammaticVideoPreparation(async request => {
      if (disabledRef.current) {
        throw new Error(translationRef.current('recipe.wizardPreparationDisabled'))
      }
      if (busyRef.current) {
        throw new Error(translationRef.current('recipe.wizardPreparationBusy'))
      }
      const currentWorkspace = workspaceRef.current
      if (currentWorkspace !== request.workspace) {
        throw new Error(translationRef.current('recipe.wizardPreparationWorkspaceMismatch', {
          expected: request.workspace,
          current: currentWorkspace,
        }))
      }
      if (pendingPreparationAckRef.current) {
        const stale = pendingPreparationAckRef.current
        pendingPreparationAckRef.current = null
        stale.reject(new Error(translationRef.current('recipe.wizardPreparationSuperseded')))
      }

      const selectedSources = [...request.outputNames]
      const loaded = selectedSources.map(name => {
        const matches = outputsRef.current.filter(output => output.name === name)
        if (!matches.length) {
          throw new Error(translationRef.current('recipe.wizardOutputMissing', { name }))
        }
        if (matches.length !== 1) {
          throw new Error(translationRef.current('recipe.wizardOutputAmbiguous', { name }))
        }
        const output = matches[0]
        if (output.type !== 'image' && output.type !== 'video' && output.type !== 'model3d') {
          throw new Error(translationRef.current('recipe.wizardOutputNonVisual', { name }))
        }
        return {
          key: output.name,
          name: output.name,
          kind: kindForOutput(output),
          source: output.name,
          previewUrl: previewForOutput(output),
        } satisfies LoadedAsset
      })
      if (workspaceRef.current !== request.workspace) {
        throw new Error(translationRef.current('recipe.wizardPreparationWorkspaceRejected'))
      }

      const accepted: ProgrammaticVideoPreparation = {
        ...request,
        intent: request.intent,
        outputNames: loaded.map(asset => asset.source),
      }
      const reflected = new Promise<ProgrammaticVideoPreparationAck>((resolve, reject) => {
        pendingPreparationAckRef.current = {
          request: accepted,
          selectedSources: accepted.outputNames,
          resolve,
          reject,
        }
      })
      setProgrammaticPreparation(accepted)
      setMode(accepted.generationPolicy === 'provided_only' ? 'manual' : 'auto')
      setNoVideoGeneration(accepted.generationPolicy === 'no_video_generation')
      setIntent(accepted.intent)
      setSelected(loaded)
      setRecipeText('')
      setPlannedRecipe(null)
      setShots([])
      setActiveShot(0)
      setError(null)
      setStatus(translationRef.current('recipe.wizardPreparationLoaded', { policy: accepted.generationPolicy }))
      return reflected
    })
    return () => {
      const pending = pendingPreparationAckRef.current
      pendingPreparationAckRef.current = null
      pending?.reject(new Error(translationRef.current('recipe.wizardPreparationUnmounted')))
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    const pending = pendingPreparationAckRef.current
    const active = programmaticPreparation
    if (!pending || !active) return
    if (pending.request !== active) return
    if (workspace !== pending.request.workspace) {
      pendingPreparationAckRef.current = null
      pending.reject(new Error(translationRef.current('recipe.wizardPreparationWorkspaceRejected')))
      setProgrammaticPreparation(null)
      setSelected([])
      setError(translationRef.current('recipe.wizardPreparationWorkspaceRejected'))
      return
    }
    const reflectedSources = selected.map(asset => asset.source)
    const sourcesMatch = reflectedSources.length === pending.selectedSources.length
      && reflectedSources.every((source, index) => source === pending.selectedSources[index])
    if (intent !== pending.request.intent || !sourcesMatch) return
    pendingPreparationAckRef.current = null
    pending.resolve({
      message: translationRef.current('recipe.wizardPreparationReady', { policy: active.generationPolicy }),
      policy: active.generationPolicy,
    })
  }, [intent, programmaticPreparation, selected, workspace])

  useEffect(() => {
    if (!programmaticPreparation || programmaticPreparation.workspace === workspace) return
    setProgrammaticPreparation(null)
    setSelected([])
    setError(translationRef.current('recipe.wizardPreparationWorkspaceCleared'))
  }, [programmaticPreparation, workspace])

  const resetProgrammaticPreparation = () => {
    const pending = pendingPreparationAckRef.current
    pendingPreparationAckRef.current = null
    pending?.reject(new Error(t('recipe.wizardPreparationReset')))
    setProgrammaticPreparation(null)
    setMode('auto')
    setNoVideoGeneration(false)
    setIntent(DEFAULT_INTENT)
    setSelected([])
    setRecipeText(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE, null, 2))
    setPlannedRecipe(null)
    setShots([])
    setActiveShot(0)
    setStatus(t('recipe.wizardPreparationReset'))
    setError(null)
  }

  const trustedPolicy = programmaticPreparation?.generationPolicy

  const applyShot = async (recipe: SceneRecipe, shot: SceneRecipeShot, resolved: Record<string, string>) => {
    const storedRecipe = withSceneGenerationPolicy(recipe, recipe.generationPolicy)
    const scene = compileRecipeShot(storedRecipe, shot, resolved, filename => getFileUrl(filename, workspace))
    await onApply({ ...storedRecipe, record: false, save: false }, scene, setStatus, intent.trim())
  }

  const setPanelBusy = (next: typeof busy) => {
    busyRef.current = next
    setBusy(next)
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

  const writeRecipe = async () => {
    if (!intent.trim()) return
    const callerPolicy = callerGenerationPolicy(mode, noVideoGeneration, trustedPolicy)
    const policyInstructions = generationPolicyInstructions(callerPolicy)
    setPanelBusy('write')
    setError(null)
    setStatus(t('recipe.interpreting'))
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
      const systemPrompt = `${buildRecipeSystemPrompt({ mode, inventory: fullInventory })}\n\n${policyInstructions}`
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
          setStatus(t('recipe.repairing', { attempt: attempt + 1, message: validationMessage }))
          text = await generateLlmText({
            prompt: `Repair your previous recipe without changing the user's intent. Preserve every valid requested subject and action, fix the validation error, and return one complete replacement JSON object.\n\n${policyInstructions}\n\nUSER INTENT:\n${intent.trim()}\n\nVALIDATION ERROR:\n${validationMessage}\n\nPREVIOUS RECIPE:\n${text.slice(0, 16_000)}`,
            system_prompt: systemPrompt,
            max_new_tokens: 4000,
            temperature: 0.05,
            top_p: 0.8,
            json_schema: SCENE_RECIPE_JSON_SCHEMA,
          })
        }
      }
      if (!recipe) throw new Error(t('recipe.invalidRecipe'))
      if (mode === 'manual') {
        recipe = constrainManualRecipeToInventory(recipe, fullInventory)
      }
      recipe = withSceneGenerationPolicy(recipe, callerPolicy)
      setRecipeText(JSON.stringify(recipe, null, 2))
      setPlannedRecipe(recipe)
      setShots(listRecipeShots(recipe))
      setActiveShot(0)
      setStatus(t('recipe.ready', { name: recipe.name, count: listRecipeShots(recipe).length }))
    } catch (reason) {
      setError(recipeErrorMessage(reason, t))
    } finally {
      setPanelBusy(null)
    }
  }

  const runRecipe = async () => {
    const callerPolicy = callerGenerationPolicy(mode, noVideoGeneration, trustedPolicy)
    abortRef.current?.abort()
    const abort = new AbortController()
    abortRef.current = abort
    setPanelBusy('run')
    setError(null)
    try {
      const recipe = withSceneGenerationPolicy(parseSceneRecipeText(recipeText), callerPolicy)
      setStatus(mode === 'manual' ? t('recipe.usingLoaded') : t('recipe.resolving'))
      const resolved = await resolveRecipeAssets(recipe, {
        workspace,
        onStatus: setStatus,
        signal: abort.signal,
        generateMissing: mode === 'auto',
        policy: callerPolicy,
      })
      const stored = withSceneGenerationPolicy(withResolvedSources(recipe, resolved), callerPolicy)
      setRecipeText(JSON.stringify(stored, null, 2))
      setPlannedRecipe(stored)
      const nextShots = listRecipeShots(stored)
      setShots(nextShots)
      setActiveShot(0)
      await applyShot(stored, nextShots[0], resolved)
      setStatus(t('recipe.mounted', { name: nextShots[0].name }))
    } catch (reason) {
      setError(recipeErrorMessage(reason, t))
    } finally {
      if (abortRef.current === abort) abortRef.current = null
      setPanelBusy(null)
    }
  }

  const mountShot = async (index: number) => {
    const callerPolicy = callerGenerationPolicy(mode, noVideoGeneration, trustedPolicy)
    setPanelBusy('run')
    setError(null)
    try {
      // Resolved sources already live in the editable JSON. Keeping a second
      // cached recipe/map can restore an earlier run after planning or editing.
      const recipe = withSceneGenerationPolicy(parseSceneRecipeText(recipeText), callerPolicy)
      const resolved = Object.fromEntries(recipe.assets.filter(asset => asset.source).map(asset => [asset.id, asset.source as string]))
      const nextShots = listRecipeShots(recipe)
      const shot = nextShots[index]
      if (!shot) return
      setActiveShot(index)
      await applyShot(recipe, shot, resolved)
      setRecipeText(JSON.stringify(recipe, null, 2))
      setPlannedRecipe(recipe)
      setShots(nextShots)
      setStatus(t('recipe.mountedEdit', { name: shot.name }))
    } catch (reason) {
      setError(recipeErrorMessage(reason, t))
    } finally {
      setPanelBusy(null)
    }
  }

  const locked = Boolean(busy) || disabled
  const wizardPolicyLocked = Boolean(programmaticPreparation)

  return (
    <div className="space-y-2 rounded border border-cyan-400/30 bg-cyan-400/[.04] p-2">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-cyan-200">
        <Sparkles size={12} /> {t('recipe.title')}
      </div>
      {programmaticPreparation && (
        <div role="status" className="space-y-1 rounded border border-amber-300/40 bg-amber-300/[.08] px-2 py-1.5 text-[9px] text-amber-100">
          <p>{t('recipe.wizardPolicyLocked', { policy: programmaticPreparation.generationPolicy })}</p>
          <button
            type="button"
            disabled={locked}
            onClick={resetProgrammaticPreparation}
            className="rounded border border-amber-200/40 px-1.5 py-0.5 text-[8px] text-amber-100 hover:bg-amber-300/10 disabled:opacity-40"
          >
            {t('recipe.resetWizardSession')}
          </button>
        </div>
      )}
      <div className="grid grid-cols-2 gap-1">
        {(['manual', 'auto'] as const).map(value => (
          <button
            key={value}
            type="button"
            disabled={locked || wizardPolicyLocked}
            onClick={() => setMode(value)}
            className={`rounded border px-2 py-1 text-[10px] ${
              mode === value ? 'border-cyan-300 bg-cyan-400/15 text-cyan-100' : 'border-border text-text-muted'
            }`}
          >
            {value === 'manual' ? t('recipe.manual') : t('recipe.auto')}
          </button>
        ))}
      </div>
      <p className="text-[8px] text-text-muted">
        {mode === 'manual' ? t('recipe.manualHelp') : t('recipe.autoHelp')}
      </p>
      {mode === 'auto' && (
        <div className="rounded border border-border bg-bg-primary/30 px-2 py-1.5">
          <label className="flex items-start gap-1.5 text-[10px] text-text-secondary">
            <input aria-label={t('recipe.noVideoGeneration')}
              type="checkbox"
              checked={noVideoGeneration}
              disabled={locked || wizardPolicyLocked}
              onChange={event => setNoVideoGeneration(event.currentTarget.checked)}
              className="mt-0.5 accent-cyan-400"
            />
            <span>{t('recipe.noVideoGeneration')}</span>
          </label>
          <p className="mt-1 pl-5 text-[8px] leading-relaxed text-text-muted">{t('recipe.noVideoGenerationHelp')}</p>
        </div>
      )}

      <details className="rounded border border-border bg-bg-primary/45 px-2 py-1.5 text-[9px] text-text-muted">
        <summary className="cursor-pointer font-medium text-text-secondary">{t('recipe.howTitle')}</summary>
        <p className="mt-1 leading-relaxed">{t('recipe.howBody')}</p>
      </details>

      {mode === 'manual' && (
        <div className="space-y-2">
          <AssetInput
            label={t('recipe.imagesFromApp')}
            placeholder={t('recipe.images')}
            items={gallery.images}
            accept="image/*,video/*"
            disabled={locked}
            constraints={{ kinds: ['image', 'video'], maxCount: 1, optional: true }}
            onChoose={item => { if (item) void addOutput(item) }}
          />
          <AssetInput
            label={t('recipe.glbFromApp')}
            placeholder={t('recipe.models')}
            items={gallery.models}
            accept=".glb,model/gltf-binary"
            disabled={locked}
            constraints={{ kinds: ['model3d'], maxCount: 1, optional: true }}
            onChoose={item => { if (item) void addOutput(item) }}
          />
          {selected.length > 0 && (
            <div>
              <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('recipe.selectedCount', { count: selected.length })}</div>
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
        </div>
      )}

      <label className="block text-[10px] text-text-muted">
        {t('recipe.describe')}
        <textarea aria-label={t('recipe.describe')}
          rows={3}
          value={intent}
          disabled={locked}
          onChange={event => setIntent(event.target.value)}
          className="mt-1 w-full resize-y rounded border border-border bg-bg-primary px-2 py-1.5 text-[10px] text-text-primary"
        />
      </label>
      <div className="flex flex-wrap gap-1" aria-label={t('recipe.examplesAria')}>
        {INTENT_EXAMPLES.map(example => (
          <button
            key={example.key}
            type="button"
            disabled={locked}
            onClick={() => setIntent(example.text)}
            className="rounded border border-border px-1.5 py-1 text-[8px] text-text-muted hover:border-cyan-400/60 hover:text-cyan-100 disabled:opacity-40"
          >
            {t(`recipe.examples.${example.key}`)}
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
          {t('recipe.planScene')}
        </button>
        <button
          type="button"
          disabled={locked}
          onClick={() => {
            setRecipeText(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE, null, 2))
            setShots(listRecipeShots(EXAMPLE_SAUCER_CRUISE_RECIPE))
            setPlannedRecipe(EXAMPLE_SAUCER_CRUISE_RECIPE)
            setActiveShot(0)
          }}
          className="flex items-center justify-center gap-1 rounded border border-border bg-bg-primary px-2 py-1.5 text-[10px] disabled:opacity-40"
        >
          <FileJson size={11} /> {t('recipe.example')}
        </button>
      </div>
      {plannedRecipe && (
        <section aria-label={t('recipe.planAria')} className="space-y-1.5 rounded border border-cyan-400/30 bg-cyan-400/[.07] p-2">
          <div className="text-[9px] font-medium uppercase tracking-wider text-cyan-100">{t('recipe.reviewPlan', { count: plannedRecipe.shots?.length || 1 })}</div>
          <div className="space-y-1">
            {plannedRecipe.assets.map(asset => (
              <p key={asset.id} className="text-[8px] leading-relaxed text-text-secondary"><span className="font-medium text-cyan-100">{asset.id}</span> — {assetPlanLabel(asset, t)}</p>
            ))}
          </div>
          <div className="space-y-1 border-t border-cyan-400/15 pt-1">
            {(plannedRecipe.shots?.length ? plannedRecipe.shots : [{ name: 'scene', duration: plannedRecipe.scene.duration, layers: plannedRecipe.scene.layers }]).map((shot, index) => (
              <p key={`${shot.name}-${index}`} className="text-[8px] text-text-muted">{index + 1}. {shot.name} · {shot.duration || plannedRecipe.scene.duration || 5}s · {shotPlanLabel(shot, t)}</p>
            ))}
          </div>
        </section>
      )}
      <details className="rounded border border-border bg-bg-primary/30 px-2 py-1.5">
        <summary className="cursor-pointer text-[9px] text-text-muted">{t('recipe.advancedJson')}</summary>
        <textarea
          aria-label={t('recipe.jsonAria')}
          rows={8}
          value={recipeText}
          disabled={locked}
          onChange={event => { setRecipeText(event.target.value); setPlannedRecipe(null); setShots([]); setActiveShot(0) }}
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
          {busy === 'run' ? t('recipe.working') : mode === 'manual' ? t('recipe.compose') : t('recipe.generateCompose')}
        </button>
        {busy && busy !== 'upload' && (
          <button
            type="button"
            onClick={() => abortRef.current?.abort()}
            className="flex items-center justify-center gap-1 rounded border border-red-400/50 px-2 py-1.5 text-[10px] text-red-200"
          >
            <Square size={10} /> {t('recipe.cancel')}
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
