import * as api from '../api/client'
import { beginImageSettingsChange, restoreStudioImageSettings } from '../features/studio/imageSettingsRestore'
import type { GenerateParams, GenerationMode } from '../types'
import { getModelMode } from './modelCatalog'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

// Monotonic sequence for loadModelOptions staleness detection — only the
// most recently requested model's options may touch the store.
export let _modelOptionsSeq = 0

export function advanceModelOptionsSeq(): number {
  return ++_modelOptionsSeq
}

export type RecipesSlice = {
  // Recipes (one-click Studio presets)
  recipesOpen: boolean
  setRecipesOpen: (open: boolean) => void
  recipes: import('../api/client').RecipeCard[]
  recipesLoading: boolean
  loadRecipes: () => Promise<void>
  applyRecipe: (id: string) => Promise<{ missing: import('../api/client').RecipeLora[] }>
  saveRecipeFromOutput: (outputName: string, name: string, description: string, nsfw: boolean) => Promise<void>
  deleteRecipe: (id: string) => Promise<void>
  downloadRecipeLora: (lora: import('../api/client').RecipeLora, modelType: string) => Promise<void>
}

/** applyRecipe passes get and set into the image-settings restore, which is typed as AppState. */
export type RecipesSliceHost = AppState

export const createRecipesSlice: SliceCreator<RecipesSlice, RecipesSliceHost> = (set, get) => ({
  // ── Recipes (one-click Studio presets) ────────────────────────────
  recipesOpen: false,
  setRecipesOpen: (open) => {
    set({ recipesOpen: open })
    if (open) get().loadRecipes()
  },
  recipes: [],
  recipesLoading: false,
  loadRecipes: async () => {
    set({ recipesLoading: true })
    try {
      const { recipes } = await api.fetchRecipes()
      set({ recipes, recipesLoading: false })
    } catch (e) {
      console.error('Failed to load recipes:', e)
      set({ recipes: [], recipesLoading: false })
    }
  },
  applyRecipe: async (id) => {
    // Applies a recipe like Load Settings applies a saved output: switch
    // model + generation mode, land the tuned params in the active Studio
    // working set, and PREPOPULATE the prompt (a real, editable value — not
    // placeholder text) so the user just tweaks the subject. Seed and repeat
    // reset so a recipe reproduces a look, not a specific frame.
    const recipeChange = beginImageSettingsChange(get)
    const recipe = await api.fetchRecipe(id)
    const { models } = get()
    const model = models.find(m => m.model_type === recipe.model_type)
    const mode = model ? getModelMode(recipe.model_type, model.family) : ((recipe.mode as GenerationMode) || 'video')
    if (mode === 'image') {
      if (!recipeChange.current()) throw new Error('The image form changed while loading the recipe')
      _modelOptionsSeq += 1
      set({ modelOptionsLoading: false })
      const restored = await restoreStudioImageSettings({ ...recipe.params, model_type: recipe.model_type,
        prompt: recipe.prompt_example || '', seed: -1,
        activated_loras: (recipe.loras || []).map(item => item.filename),
        loras_multipliers: (recipe.loras || []).map(item => String(item.multiplier ?? 1)).join(' '),
      }, get().activeWorkspace, get, set)
      if (!restored) throw new Error('The image form changed while loading the recipe')
      await get().loadLoras(recipe.model_type)
      const present = new Set(get().availableLoras.map(name => name.replace(/\\/g, '/').split('/').pop()))
      return { missing: (recipe.loras || []).filter(item => !present.has(item.filename)) }
    }

    const activated = (recipe.loras || []).map(l => l.filename)
    const multipliers = (recipe.loras || []).map(l => String(l.multiplier ?? '1.0')).join(' ')
    const loraWeights: Record<string, number[]> = {}
    for (const l of recipe.loras || []) {
      loraWeights[l.filename] = String(l.multiplier ?? '1.0').split(';').map(Number)
    }

    set(s => ({
      generationMode: mode,
      // NOTE: do NOT close the overlay here. The RecipesOverlay closes
      // itself on success, but keeps itself open when the recipe needs
      // LoRAs you don't have — so it can show the download prompt. Closing
      // here made that prompt dead code (recipe applied, LoRA missing, user
      // generated → cryptic "Loras missing" failure with no guidance).
      params: {
        ...s.params,
        ...(recipe.params as Partial<GenerateParams>),
        model_type: recipe.model_type,
        prompt: recipe.prompt_example || '',
        activated_loras: activated,
        loras_multipliers: multipliers,
        seed: -1,
        repeat_generation: 1,
        // Recipes are look presets — land in the base Studio sub-mode
        // (Frames for video, image-output for image), not Extend/Blend.
        image_mode: 0,
      },
      loraWeights,
      availableLoras: [],
      selectedModelPerMode: { ...s.selectedModelPerMode, [mode]: recipe.model_type },
      h3WindowPlan: null,
    }))

    if (recipe.model_type) {
      get().loadModelOptions(recipe.model_type)
      // Derive duration from video_length if the recipe carried one.
      const vlen = (recipe.params as Record<string, unknown>)?.video_length
      const fps = model?.fps || 16
      if (typeof vlen === 'number' && vlen > 0) {
        set({ durationSeconds: Math.round((vlen / fps) * 10) / 10 })
      }
      // Await the LoRA list so we can report which recipe LoRAs are missing.
      await get().loadLoras(recipe.model_type)
    }

    const present = new Set(get().availableLoras.map(x => (x || '').replace(/\\/g, '/').split('/').pop() || ''))
    const missing = (recipe.loras || []).filter(l => !present.has(l.filename))
    return { missing }
  },
  saveRecipeFromOutput: async (outputName, name, description, nsfw) => {
    await api.saveRecipeFromOutput({ output_name: outputName, name, description, nsfw })
    if (get().recipesOpen) get().loadRecipes()
  },
  deleteRecipe: async (id) => {
    await api.deleteRecipe(id)
    set(s => ({ recipes: s.recipes.filter(r => r.id !== id) }))
  },
  downloadRecipeLora: async (lora, modelType) => {
    // Best-effort fetch of a recipe's LoRA from its CivitAI source. Portable
    // recipes carry a direct download_url in source_url; if it isn't a
    // CivitAI URL the backend rejects it and the UI falls back to the link.
    if (!lora.source_url) throw new Error('This recipe has no download source for that LoRA — install it manually.')
    const model = get().models.find(m => m.model_type === modelType)
    await api.startCivitAIDownload({
      download_url: lora.source_url,
      filename: lora.filename,
      // architecture (not family) is what the backend's get_lora_dir keys on,
      // so the LoRA lands in the same per-model dir the model loads from.
      target_arch: (model?.architecture as string) || '',
      model_id: 0, version_id: 0, trained_words: [],
      model_name: lora.filename, images: [],
    })
    get().pollCivitAIDownloads()
  },
})
