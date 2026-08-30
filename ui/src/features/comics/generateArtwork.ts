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

export async function generateDirectorArtwork(options: {
  force?: boolean
  onProgress?: (message: string, current: number, total: number) => void
}): Promise<{ generated: number; total: number }> {
  const state = useComicStore.getState()
  const director = state.project.director
  if (!director) throw new Error('Este cómic no tiene plan de Director; no puedo dibujar las viñetas.')
  const tasks: Array<{ pageId: string; panel: ComicPanelElement; plan: ComicPlanPanel }> = []
  director.plan.pages.forEach((planPage, pageIndex) => {
    const page = state.project.pages[pageIndex]
    const panels = page?.elements.filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((a, b) => a.zIndex - b.zIndex) || []
    planPage.panels.forEach((planned, index) => {
      if ((options.force || !director.completedPanelIds.includes(planned.id)) && panels[index]) {
        tasks.push({ pageId: page.id, panel: panels[index], plan: planned })
      }
    })
  })
  if (!tasks.length) return { generated: 0, total: 0 }

  for (let index = 0; index < tasks.length; index += 1) {
    const task = tasks[index]
    options.onProgress?.(
      `Generando la viñeta ${index + 1} de ${tasks.length}…`,
      index + 1,
      tasks.length,
    )
    const currentDirector = useComicStore.getState().project.director!
    const identityReference = panelIdentityReference(
      currentDirector,
      task.plan,
      useComicStore.getState().project.assets,
    )
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
    let asset = null
    if (
      currentDirector.provider === 'maestro'
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
          `Recuperada la ilustración terminada para la viñeta ${index + 1}.`,
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
            `Conexión interrumpida al comprobar la viñeta ${index + 1}; reintentando (${attempt}/20)…`,
            index + 1,
            tasks.length,
          ),
          onProviderRetry: attempt => options.onProgress?.(
            `El proveedor falló temporalmente en la viñeta ${index + 1}; reintentando (${attempt}/2)…`,
            index + 1,
            tasks.length,
          ),
          aspectRatio: miniMaxAspectRatio(task.panel.width, task.panel.height),
        },
      )
    }
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
    latest.patchProject({
      director: {
        ...latest.project.director!,
        completedPanelIds: Array.from(new Set([
          ...latest.project.director!.completedPanelIds,
          task.plan.id,
        ])),
        panelJobs: Object.fromEntries(
          Object.entries(latest.project.director!.panelJobs || {})
            .filter(([panelId]) => panelId !== task.plan.id),
        ),
      },
    })
    await useStore.getState().loadOutputs()
  }
  return { generated: tasks.length, total: tasks.length }
}
