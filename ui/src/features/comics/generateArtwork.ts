import { findCompletedLocalImage, generateImageAsset } from '../../lib/imageGeneration'
import { useStore } from '../../stores/useStore'
import { comicId, repairMojibake } from './model'
import { useComicStore } from './store'
import type { ComicPanelElement, ComicPlanPanel, ComicProject } from './types'

export function panelIdentityReference(
  director: NonNullable<ComicProject['director']>,
  panel: ComicPlanPanel,
  assets: ComicProject['assets'],
): { source?: string; characterId?: string } {
  const characters = new Map(director.plan.characters.map(character => [character.id, character]))
  for (const characterId of panel.characters) {
    const character = characters.get(characterId)
    if (!character) continue
    const referenceIds = Array.from(new Set([
      character.referenceAssetId,
      ...(character.referenceAssetIds || []),
    ].filter((value): value is string => Boolean(value))))
    const asset = referenceIds.map(id => assets[id]).find(Boolean)
    if (asset?.source) return { source: asset.source, characterId }
  }
  return {}
}

export function miniMaxAspectRatio(
  width: number,
  height: number,
): NonNullable<Parameters<typeof generateImageAsset>[5]>['aspectRatio'] {
  const target = Math.max(0.01, width / Math.max(1, height))
  const ratios = [
    ['1:1', 1], ['16:9', 16 / 9], ['4:3', 4 / 3], ['3:2', 3 / 2],
    ['2:3', 2 / 3], ['3:4', 3 / 4], ['9:16', 9 / 16], ['21:9', 21 / 9],
  ] as const
  return ratios.reduce((best, candidate) =>
    Math.abs(Math.log(candidate[1] / target)) < Math.abs(Math.log(best[1] / target))
      ? candidate : best)[0]
}

export function buildDirectorImagePrompt(
  director: ComicProject['director'],
  panelPrompt: string,
  promptSuffix: string,
  plannedPanel?: ComicPlanPanel,
): string {
  const input = director?.input
  const removePageLayoutInstructions = (value: string) => repairMojibake(value)
    .replace(/\b(?:estructura|structure|layout)\s*:\s*[^.!?]*(?:p[aá]ginas?|pages?|paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/[^.!?]*(?:\d+\s+)?(?:p[aá]ginas?|pages?)[^.!?]*(?:paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/\bprofessional sequential comic art\b/gi, 'single comic-panel illustration')
    .replace(/\s+/g, ' ')
    .trim()
  const visualBible = removePageLayoutInstructions(director?.plan.styleBible || '')
  let repairedPanelPrompt = removePageLayoutInstructions(panelPrompt)
  if (visualBible) {
    const bibleTextIndex = repairedPanelPrompt.indexOf(visualBible)
    const bibleLabelIndex = repairedPanelPrompt
      .slice(0, Math.max(0, bibleTextIndex))
      .toLocaleLowerCase()
      .lastIndexOf('visual continuity bible:')
    if (bibleTextIndex >= 0 && bibleLabelIndex >= 0) {
      repairedPanelPrompt = `${repairedPanelPrompt.slice(0, bibleLabelIndex)} ${
        repairedPanelPrompt.slice(bibleTextIndex + visualBible.length).replace(/^[.\s]+/, '')
      }`.replace(/\s+/g, ' ').trim()
    }
  }
  const characterLocks = plannedPanel?.characters.map(characterId => {
    const character = director?.plan.characters.find(item => item.id === characterId)
    if (!character) return ''
    return [
      `${character.name}: ${character.description}`,
      character.visualNotes,
      character.wardrobe,
      character.negativePrompt ? `Never alter or add: ${character.negativePrompt}` : '',
    ].filter(Boolean).join('. ')
  }).filter(Boolean).join(' | ')
  const storyboard = input?.productionMode === 'storyboard'
  const singleImageLock = storyboard
    ? 'STORYBOARD FRAME LOCK: Create exactly one full-bleed cinematic first frame in the requested video aspect ratio. No storyboard sheet, comic page, panel grid, collage, split screen, inset frame, border, speech bubble, caption, sound effect, subtitle, logo, watermark or lettering.'
    : 'SINGLE IMAGE LOCK: Create exactly one full-bleed illustration for one comic panel. No comic page, panel grid, collage, split screen, inset panels, frames, borders, speech bubbles, captions, sound effects, text, logos, watermarks or lettering.'
  const fullPrompt = [
    singleImageLock,
    input?.artStyle ? `VISUAL STYLE LOCK: ${removePageLayoutInstructions(input.artStyle)}.` : '',
    input?.worldContext ? `WORLD AND PERIOD LOCK: ${removePageLayoutInstructions(input.worldContext)}.` : '',
    visualBible && !repairedPanelPrompt.includes(visualBible)
      ? `VISUAL CONTINUITY BIBLE: ${visualBible}.`
      : '',
    input?.forbiddenElements
      ? `STRICTLY FORBIDDEN: ${repairMojibake(input.forbiddenElements)}. No anachronisms.`
      : '',
    characterLocks ? `CHARACTER IDENTITY LOCKS: ${characterLocks}. Keep face, body, scale, palette, wardrobe and invariant accessories identical to every prior appearance.` : '',
    plannedPanel?.continuityNotes ? `SHOT CONTINUITY: ${plannedPanel.continuityNotes}.` : '',
    repairedPanelPrompt,
    removePageLayoutInstructions(promptSuffix),
  ].filter(Boolean).join(' ')
  if (director?.provider !== 'minimax' || fullPrompt.length < 1500) return fullPrompt

  const trimSection = (value: string, limit: number) => {
    if (value.length <= limit) return value
    const prefix = value.slice(0, limit)
    const lastSpace = prefix.lastIndexOf(' ')
    const clipped = (lastSpace > limit * 0.6 ? prefix.slice(0, lastSpace) : prefix)
      .replace(/[\s,;:-]+$/, '')
    return `${clipped}.`
  }
  const compactSections = [
    storyboard
      ? 'One full-bleed cinematic first frame only. No storyboard sheet, grid, collage, border, bubbles, captions, subtitles, text, logo or watermark.'
      : 'One full-bleed comic-panel illustration only. No grid, collage, border, bubbles, captions, text, logo or watermark.',
    trimSection(repairedPanelPrompt, 780),
    characterLocks ? `Character locks: ${trimSection(characterLocks, 260)}.` : '',
    input?.artStyle ? `Style: ${trimSection(removePageLayoutInstructions(input.artStyle), 140)}.` : '',
    input?.worldContext ? `World: ${trimSection(removePageLayoutInstructions(input.worldContext), 140)}.` : '',
    input?.forbiddenElements ? `Avoid: ${trimSection(repairMojibake(input.forbiddenElements), 120)}.` : '',
    plannedPanel?.continuityNotes ? `Continuity: ${trimSection(plannedPanel.continuityNotes, 120)}.` : '',
    visualBible ? `Visual continuity: ${trimSection(visualBible, 220)}.` : '',
    trimSection(removePageLayoutInstructions(promptSuffix), 100),
  ].filter(Boolean)
  let compactPrompt = ''
  for (const section of compactSections) {
    const available = 1450 - compactPrompt.length - (compactPrompt ? 1 : 0)
    if (available < 24) break
    compactPrompt += `${compactPrompt ? ' ' : ''}${trimSection(section, available)}`
  }
  return compactPrompt
}

function rememberPanelJob(panelId: string, jobId?: string): void {
  const state = useComicStore.getState()
  const director = state.project.director
  if (!director) return
  const panelJobs = { ...(director.panelJobs || {}) }
  if (jobId) panelJobs[panelId] = jobId
  else delete panelJobs[panelId]
  state.patchProject({ director: { ...director, panelJobs } })
}

export type ComicArtworkScope = 'all' | 'missing' | 'failed'

export interface ComicArtworkInventory {
  projectId: string
  title: string
  pages: number
  panels: number
  completed: number
  failed: number
  pending: number
  provider: 'maestro' | 'minimax' | ''
  activePage: number
}

export interface ComicArtworkTask {
  pageIndex: number
  panelIndex: number
  pageNumber: number
  panelNumber: number
  globalIndex: number
  pageId: string
  panel: ComicPanelElement
  plan: ComicPlanPanel
}

export interface ComicArtworkBatchResult {
  generated: number
  failed: number
  total: number
  cancelled: boolean
}

let comicBatchDepth = 0
let comicBatchCancel = false

export function requestComicArtworkCancel(): boolean {
  if (comicBatchDepth < 1) return false
  comicBatchCancel = true
  return true
}

export function comicArtworkInventory(project = useComicStore.getState().project): ComicArtworkInventory {
  const director = project.director
  const pages = director?.plan.pages.length || project.pages.length
  const panels = director?.plan.pages.reduce((sum, page) => sum + page.panels.length, 0) || 0
  const completed = director?.completedPanelIds.length || 0
  const failed = director?.failedPanelIds?.length || 0
  const firstPendingPage = director?.plan.pages.findIndex((page, pageIndex) =>
    page.panels.some(panel => !director.completedPanelIds.includes(panel.id)
      && (project.pages[pageIndex]?.elements.some(element => element.type === 'panel') ?? false)))
  return {
    projectId: project.id,
    title: project.title,
    pages,
    panels,
    completed,
    failed,
    pending: Math.max(0, panels - completed),
    provider: director?.provider || '',
    activePage: (firstPendingPage ?? 0) + 1,
  }
}

export function formatComicArtworkProgress(task: ComicArtworkTask, pages: number, panels: number): string {
  return `página ${task.pageNumber}/${pages} · viñeta ${task.globalIndex}/${panels}`
}

export function selectComicArtworkTasks(
  project: ComicProject,
  options: {
    force?: boolean
    target?: { pageNumber: number; panelNumber: number }
    scope?: ComicArtworkScope
    pages?: number[]
  } = {},
): ComicArtworkTask[] {
  const director = project.director
  if (!director) return []
  const completed = new Set(director.completedPanelIds)
  const failed = new Set(director.failedPanelIds || [])
  const pageFilter = options.pages?.length ? new Set(options.pages) : null
  const scope: ComicArtworkScope = options.scope
    || (options.force || options.target ? 'all' : 'missing')
  const tasks: ComicArtworkTask[] = []
  let globalIndex = 0
  director.plan.pages.forEach((planPage, pageIndex) => {
    const page = project.pages[pageIndex]
    const panels = page?.elements.filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((left, right) => left.zIndex - right.zIndex) || []
    planPage.panels.forEach((planned, index) => {
      globalIndex += 1
      const pageNumber = pageIndex + 1
      const panelNumber = index + 1
      if (pageFilter && !pageFilter.has(pageNumber)) return
      if (options.target && (options.target.pageNumber !== pageNumber || options.target.panelNumber !== panelNumber)) return
      const include = options.target
        || scope === 'all'
        || (scope === 'failed' ? failed.has(planned.id) : !completed.has(planned.id))
      if (include && panels[index]) {
        tasks.push({
          pageIndex,
          panelIndex: index,
          pageNumber,
          panelNumber,
          globalIndex,
          pageId: page.id,
          panel: panels[index],
          plan: planned,
        })
      }
    })
  })
  return tasks
}

export async function generateDirectorArtwork(options: {
  force?: boolean
  target?: { pageNumber: number; panelNumber: number }
  scope?: ComicArtworkScope
  pages?: number[]
  onProgress?: (message: string, current: number, total: number) => void
  drawPanel?: (task: ComicArtworkTask) => Promise<import('./types').ComicAsset>
}): Promise<ComicArtworkBatchResult> {
  const state = useComicStore.getState()
  const director = state.project.director
  if (!director) throw new Error('Este cómic no tiene plan de Director; no puedo dibujar las viñetas.')
  const inventory = comicArtworkInventory(state.project)
  const tasks = selectComicArtworkTasks(state.project, options)
  if (options.target && !tasks.length) {
    throw new Error(`No existe la viñeta ${options.target.panelNumber} en la página ${options.target.pageNumber}.`)
  }
  if (!tasks.length) return { generated: 0, failed: 0, total: 0, cancelled: false }

  comicBatchDepth += 1
  comicBatchCancel = false
  let generated = 0
  let failed = 0
  try {
    for (let index = 0; index < tasks.length; index += 1) {
      if (comicBatchCancel) {
        return { generated, failed, total: tasks.length, cancelled: true }
      }
      const task = tasks[index]
      options.onProgress?.(
        `Generando ${formatComicArtworkProgress(task, inventory.pages, inventory.panels)}…`,
        index + 1,
        tasks.length,
      )
      try {
        const currentDirector = useComicStore.getState().project.director!
        const identityReference = panelIdentityReference(
          currentDirector,
          task.plan,
          useComicStore.getState().project.assets,
        )
        let asset = options.drawPanel ? await options.drawPanel(task) : null
        if (!asset && !options.drawPanel) {
          const maestroState = useStore.getState()
          const selectedImageModel = maestroState.models.find(model =>
            model.model_type === currentDirector.imageModel)
          const localSupportsReferences = currentDirector.provider === 'maestro'
            && Boolean(
              selectedImageModel?.supports_ref_images
              || (currentDirector.imageModel === maestroState.params.model_type
                && maestroState.modelOptions?.image_ref_choices),
            )
          const worldReferenceId = currentDirector.input.worldReferenceAssetIds?.[0]
          const reference = identityReference.source || (localSupportsReferences && worldReferenceId
            ? useComicStore.getState().project.assets[worldReferenceId]?.source
            : undefined)
          const prompt = buildDirectorImagePrompt(
            currentDirector,
            task.plan.imagePrompt,
            state.project.style.promptSuffix,
            task.plan,
          )
          const existingJobId = currentDirector.panelJobs?.[task.plan.id]
          if (
            currentDirector.provider === 'maestro'
            && !options.force
            && !options.target
            && !existingJobId
            && currentDirector.completedPanelIds.length > 0
            && currentDirector.imageModel
          ) {
            const assignedNames = new Set(
              Object.values(useComicStore.getState().project.assets).map(item => item.name),
            )
            asset = await findCompletedLocalImage(prompt, currentDirector.imageModel, assignedNames)
            if (asset) {
              options.onProgress?.(
                `Recuperada ${formatComicArtworkProgress(task, inventory.pages, inventory.panels)}.`,
                index + 1,
                tasks.length,
              )
            }
          }
          if (!asset) {
            asset = await generateImageAsset(
              currentDirector.provider,
              prompt,
              currentDirector.imageModel,
              reference,
              '',
              {
                panelId: task.plan.id,
                existingJobId,
                onJobSubmitted: jobId => rememberPanelJob(task.plan.id, jobId),
                onPollRetry: attempt => options.onProgress?.(
                  `Conexión interrumpida en ${formatComicArtworkProgress(task, inventory.pages, inventory.panels)}; reintentando (${attempt}/20)…`,
                  index + 1,
                  tasks.length,
                ),
                onProviderRetry: attempt => options.onProgress?.(
                  `El proveedor falló temporalmente en ${formatComicArtworkProgress(task, inventory.pages, inventory.panels)}; reintentando (${attempt}/2)…`,
                  index + 1,
                  tasks.length,
                ),
                aspectRatio: miniMaxAspectRatio(task.panel.width, task.panel.height),
              },
            )
          }
        }
        if (!asset) throw new Error('El proveedor no devolvió una ilustración.')
        if (identityReference.characterId) asset.characterIds = [identityReference.characterId]
        const latest = useComicStore.getState()
        const latestPage = latest.project.pages.find(page => page.id === task.pageId)
        latestPage?.elements
          .filter(element => element.parentId === task.panel.id && element.type === 'image')
          .forEach(element => latest.removeElement(task.pageId, element.id))
        latest.addAsset(asset)
        latest.addElement(task.pageId, {
          id: comicId('image'), type: 'image', assetId: asset.id, parentId: task.panel.id,
          x: 0, y: 0, width: task.panel.width, height: task.panel.height,
          rotation: 0, zIndex: 2, objectFit: 'cover', filter: 'none', opacity: 1, visible: true,
        })
        const after = useComicStore.getState().project.director!
        latest.patchProject({
          director: {
            ...after,
            completedPanelIds: Array.from(new Set([...after.completedPanelIds, task.plan.id])),
            failedPanelIds: (after.failedPanelIds || []).filter(id => id !== task.plan.id),
            panelJobs: Object.fromEntries(
              Object.entries(after.panelJobs || {}).filter(([panelId]) => panelId !== task.plan.id),
            ),
          },
        })
        generated += 1
        if (!options.drawPanel) await useStore.getState().loadOutputs()
      } catch (error) {
        failed += 1
        const latest = useComicStore.getState()
        const after = latest.project.director
        if (after) {
          latest.patchProject({
            director: {
              ...after,
              failedPanelIds: Array.from(new Set([...(after.failedPanelIds || []), task.plan.id])),
            },
          })
        }
        options.onProgress?.(
          `Falló ${formatComicArtworkProgress(task, inventory.pages, inventory.panels)}: ${error instanceof Error ? error.message : String(error)}`,
          index + 1,
          tasks.length,
        )
      }
    }
    return { generated, failed, total: tasks.length, cancelled: false }
  } finally {
    comicBatchDepth = Math.max(0, comicBatchDepth - 1)
    comicBatchCancel = false
  }
}
