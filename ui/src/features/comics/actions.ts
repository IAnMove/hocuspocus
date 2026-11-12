import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { contentLanguageForUi, scaffoldLanguage } from '../../lib/contentLanguage'
import i18n from '../../i18n'
import { useStore } from '../../stores/useStore'
import { compileProviderPrompt, mergeLanguageIntent } from '../../lib/languageIntent'
import type { CreateComicCommand, GenerateComicCommand } from './commands'

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function comicResult(
  project: { id: string; title: string },
  message: string,
  extra: {
    status?: CommandResult['status']
    generated?: number
    failed?: number
    cancelled?: boolean
  } = {},
): CommandResult {
  const entity = { kind: 'comic', id: project.id, workspaceId: workspaceName() }
  return commandResultFromSlice({
    status: extra.status,
    entity,
    navigationTarget: { destination: 'comics', entity },
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'comics:reply',
      metadata: {
        summary: message,
        title: project.title,
        ...(extra.generated == null ? {} : { generated: extra.generated }),
        ...(extra.failed == null ? {} : { failed: extra.failed }),
        ...(extra.cancelled == null ? {} : { cancelled: extra.cancelled }),
      },
    }],
  })
}

export async function createFilledComic(action: CreateComicCommand): Promise<CommandResult> {
  const [{ useComicStore }, { comicId, projectFromPlan }] = await Promise.all([
    import('./store'),
    import('./model'),
  ])
  const authoredLanguage = action.language || contentLanguageForUi().language
  const lng = scaffoldLanguage(authoredLanguage)
  const characters = (action.characters.length ? action.characters : [{
    name: i18n.t('comics:scaffold.leadName', { lng }),
    role: i18n.t('comics:scaffold.roleLead', { lng }),
    personality: '',
    desire: '',
    flaw: '',
    appearance: i18n.t('comics:scaffold.appearance', { lng }),
    voice: '',
  }]).map((character, index) => ({
    id: comicId('character'),
    name: character.name || i18n.t('comics:scaffold.characterName', { lng, index: index + 1 }),
    description: character.appearance || character.role || character.name,
    role: character.role || (index
      ? i18n.t('comics:scaffold.roleSupport', { lng })
      : i18n.t('comics:scaffold.roleLead', { lng })),
    personality: character.personality,
    motivation: character.desire,
    voice: character.voice,
    wardrobe: character.appearance || i18n.t('comics:scaffold.wardrobe', { lng }),
    visualNotes: [character.appearance, action.styleName, i18n.t('comics:scaffold.visualNotes', { lng })].filter(Boolean).join('. '),
    negativePrompt: 'inconsistent face, changed wardrobe, duplicate character, extra limbs, unreadable silhouette',
    referenceAssetIds: [],
    locked: false,
  }))
  const panels = action.panels.length ? action.panels : [
    { caption: action.synopsis || action.title, dialogue: '', sfx: '', scene: action.synopsis },
  ]
  const requestedPages = action.pages.length ? action.pages : [{
    title: i18n.t('comics:scaffold.pageTitle', { lng, number: 1 }),
    stage: '',
    panels,
  }]
  const allPanels = requestedPages.flatMap(page => page.panels)
  const languageIntent = mergeLanguageIntent(undefined, action.languageIntent, {
    contentLanguage: authoredLanguage,
    technicalPromptLanguage: 'en',
  })
  const ending = allPanels.at(-1)?.dialogue
    || allPanels.at(-1)?.caption
    || i18n.t('comics:scaffold.ending', { lng, title: action.title })
  const castBible = characters.map(character => [
    `${character.name} (${character.role || i18n.t('comics:scaffold.roleFallback', { lng })})`,
    character.description,
    character.personality,
    character.motivation,
  ].filter(Boolean).join(': ')).join('\n')
  const storyContext = [
    `Premisa: ${action.synopsis || action.title}`,
    `Personajes:\n${castBible}`,
    `Progresión: ${requestedPages.map((page, index) => `${index + 1}. ${page.title}: ${page.stage || page.panels[0]?.scene || page.panels[0]?.caption}`).join(' → ')}`,
    `Final: ${ending}`,
  ].join('\n\n')
  const worldContext = [
    `Universo visual de “${action.title}”.`,
    action.synopsis,
    `Mantener localizaciones, época, escala y utilería coherentes durante ${requestedPages.length} páginas y ${allPanels.length} viñetas.`,
  ].filter(Boolean).join(' ')
  const forbiddenElements = [
    'No cambiar el diseño, la edad aparente, la paleta ni el vestuario de los personajes entre viñetas.',
    'No añadir texto, bocadillos, marcos, cuadrículas, logotipos ni marcas de agua dentro de las imágenes generadas.',
    'No duplicar personajes ni introducir elementos ajenos a la escena.',
  ].join(' ')
  const planId = comicId('plan')
  const plan = {
    version: 1 as const,
    id: planId,
    title: action.title,
    logline: action.synopsis,
    synopsis: action.synopsis || action.title,
    language: languageIntent.contentLanguage || authoredLanguage,
    styleBible: action.styleName || i18n.t('comics:scaffold.styleBible', { lng }),
    characters,
    storyStructure: requestedPages.map((page, pageIndex) => ({
      pageNumber: pageIndex + 1, stage: page.stage || page.title,
      goal: i18n.t('comics:scaffold.stageGoal', { lng, title: page.title }),
      turningPoint: page.panels.at(-1)?.dialogue || page.panels.at(-1)?.caption || page.stage || page.title,
    })),
    pages: requestedPages.map((page, pageIndex) => ({
      pageNumber: pageIndex + 1,
      layoutHint: 'grid' as const,
      panels: page.panels.map((panel, index) => {
        const beat = panel.scene || panel.caption || panel.dialogue || action.synopsis
        const who = characters.map(character => `${character.name}: ${character.description}`).join('; ')
        return {
          id: comicId('panel-plan'),
          order: index + 1,
          narrativeRole: i18n.t('comics:scaffold.narrativeRole', { lng, page: page.title, number: index + 1 }),
          sceneDescription: beat,
          imagePrompt: compileProviderPrompt([
            `Single comic panel for "${action.title}".`,
            action.styleName,
            beat ? `Scene: ${beat}.` : '',
            who ? `Characters: ${who}.` : '',
            'Clear acting, readable silhouette, no lettering, no balloons, no captions.',
          ].filter(Boolean).join(' '), languageIntent, { medium: 'image' }),
          characters: characters.map(character => character.id),
          framing: 'medium',
          dialogue: panel.dialogue ? [{ text: panel.dialogue, bubbleType: 'speech' as const }] : [],
          captions: panel.caption ? [panel.caption] : [],
          soundEffects: panel.sfx ? [panel.sfx] : [],
          continuityNotes: i18n.t('comics:scaffold.continuity', { lng, number: Math.max(1, index) }),
        }
      }),
    })),
  }
  const project = projectFromPlan(plan)
  project.languageIntent = languageIntent
  if (action.styleName) {
    project.style = {
      ...project.style,
      name: action.styleName,
      promptSuffix: `${action.styleName}. Consistent character design, readable acting, coherent palette and continuity across panels.`,
    }
  }
  const studio = useStore.getState()
  const provider = action.imageProvider === 'minimax' ? 'minimax' as const
    : action.imageProvider === 'maestro' ? 'maestro' as const
      : studio.productionProfile.image.provider === 'minimax' ? 'minimax' as const : 'maestro' as const
  const localProfileModel = studio.productionProfile.image.provider === 'minimax'
    ? ''
    : studio.productionProfile.image.model
  const imageModel = action.imageModel || (provider === 'minimax'
    ? 'image-01'
    : localProfileModel || studio.selectedModelPerMode.image || '')
  project.director = {
    planId,
    provider,
    imageModel,
    input: {
      useGlobalProfile: true,
      premise: action.synopsis || action.title,
      storyContext: compileProviderPrompt(storyContext, languageIntent, { medium: 'comic' }),
      productionMode: 'comic',
      pageCount: requestedPages.length,
      language: languageIntent.contentLanguage || authoredLanguage,
      format: project.format.preset,
      panelsPerPage: Math.max(...requestedPages.map(page => page.panels.length)),
      genre: 'Comedy',
      tone: 'Warm',
      audience: 'General',
      artStyle: action.styleName,
      worldContext,
      forbiddenElements,
      dialogueDensity: 'medium',
      provider,
      imageModel,
      characters,
      ending,
    },
    plan,
    completedPanelIds: [],
    failedPanelIds: [],
    panelJobs: {},
    factualBiography: action.factualBiography === true,
    scriptVersion: 1,
    scriptApprovedAt: new Date().toISOString(),
  }
  useComicStore.getState().setProject(project)
  useComicStore.setState({ dirty: true })
  const stored = useComicStore.getState().project
  const storedPanels = stored.pages.reduce((sum, page) => (
    sum + page.elements.filter(element => element.type === 'panel' && !element.parentId).length
  ), 0)
  if (stored.pages.length !== requestedPages.length || storedPanels !== allPanels.length) {
    throw new Error(i18n.t('comics:actionErrors.storedMismatch', {
      storedPages: stored.pages.length,
      storedPanels,
      requestedPages: requestedPages.length,
      requestedPanels: allPanels.length,
    }))
  }
  const imageSource = provider === 'minimax' ? 'MiniMax image-01' : imageModel || i18n.t('comics:replies.selectedLocalModel')
  return comicResult(
    project,
    i18n.t('comics:replies.created', {
      title: project.title,
      pages: requestedPages.length,
      characters: characters.length,
      panels: allPanels.length,
      imageSource,
    }),
  )
}

export async function generateFilledComicArtwork(
  action: GenerateComicCommand,
  onProgress?: (message: string) => void,
): Promise<CommandResult> {
  const [{ useComicStore }, { comicId }, { generateDirectorArtwork }] = await Promise.all([
    import('./store'),
    import('./model'),
    import('./generateArtwork'),
  ])
  const state = useComicStore.getState()
  if (!state.project.director) {
    const project = state.project
    const lng = scaffoldLanguage(project.language)
    const characters = (project.characters.length ? project.characters : [{
      id: comicId('character'),
      name: i18n.t('comics:scaffold.leadName', { lng }),
      description: i18n.t('comics:scaffold.appearance', { lng }),
      locked: false,
    }]).map(character => ({
      ...character,
      role: character.role || i18n.t('comics:scaffold.roleLead', { lng }),
      personality: character.personality || i18n.t('comics:scaffold.personality', { lng }),
      motivation: character.motivation || project.synopsis || i18n.t('comics:scaffold.motivation', { lng }),
      voice: character.voice || i18n.t('comics:scaffold.voice', { lng }),
      wardrobe: character.wardrobe || character.description || i18n.t('comics:scaffold.wardrobe', { lng }),
      visualNotes: character.visualNotes || `${character.description}. ${i18n.t('comics:scaffold.visualNotes', { lng })}`,
      negativePrompt: character.negativePrompt || 'inconsistent face, changed wardrobe, duplicate character, extra limbs',
      referenceAssetIds: character.referenceAssetIds || [],
    }))
    const pages = project.pages.map((page, pageIndex) => {
      const panels = page.elements
        .filter(element => element.type === 'panel' && !element.parentId)
        .sort((left, right) => left.zIndex - right.zIndex)
      return {
        pageNumber: pageIndex + 1,
        layoutHint: 'grid' as const,
        panels: panels.map((panel, index) => {
          const texts = page.elements.filter(element => element.type === 'text' && element.parentId === panel.id)
          const captions = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'caption' || text.bubble === 'caption'))
            .map(text => text.type === 'text' ? text.content : '')
          const soundEffects = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'sound-effect' || text.bubble === 'burst'))
            .map(text => text.type === 'text' ? text.content : '')
          const dialogue = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'dialogue' || text.bubble === 'speech'))
            .map(text => text.type === 'text' ? text.content : '')
            .filter(content => !captions.includes(content) && !soundEffects.includes(content))
          const beat = captions[0] || dialogue[0] || project.synopsis || project.title
          return {
            id: comicId('panel-plan'),
            order: index + 1,
            narrativeRole: i18n.t('comics:scaffold.narrativeRole', { page: pageIndex + 1, number: index + 1, lng }),
            sceneDescription: beat,
            imagePrompt: compileProviderPrompt([
              `Single comic panel for "${project.title}".`,
              project.style.name,
              beat ? `Scene: ${beat}.` : '',
              'Clear acting, readable silhouette, no lettering, no balloons, no captions.',
            ].filter(Boolean).join(' '), project.languageIntent, { medium: 'image' }),
            characters: characters.map(character => character.id),
            framing: 'medium',
            dialogue: dialogue.map(text => ({ text, bubbleType: 'speech' as const })),
            captions,
            soundEffects,
            continuityNotes: i18n.t('comics:scaffold.continuity', { number: Math.max(1, index), lng }),
          }
        }),
      }
    })
    if (!pages.some(page => page.panels.length)) {
      throw new Error(i18n.t('comics:actionErrors.noPanels'))
    }
    const studio = useStore.getState()
    const provider = studio.productionProfile.image.provider === 'minimax' ? 'minimax' as const : 'maestro' as const
    const imageModel = studio.productionProfile.image.model || studio.selectedModelPerMode.image || ''
    const plan = {
      version: 1 as const,
      id: comicId('plan'),
      title: project.title,
      logline: project.synopsis,
      synopsis: project.synopsis || project.title,
      language: project.language,
      styleBible: project.style.name,
      characters,
      storyStructure: pages.map((page, index) => ({
        pageNumber: page.pageNumber,
        stage: i18n.t('comics:scaffold.stage', { number: index + 1, total: pages.length, lng }),
        goal: project.synopsis || i18n.t('comics:scaffold.advanceTitle', { title: project.title, lng }),
        turningPoint: page.panels.at(-1)?.dialogue.at(-1)?.text
          || page.panels.at(-1)?.captions.at(-1)
          || i18n.t('comics:scaffold.closePageBeat', { page: page.pageNumber, lng }),
      })),
      pages,
    }
    const storyContext = [
      `Premisa: ${project.synopsis || project.title}`,
      `Personajes: ${characters.map(character => `${character.name}: ${character.description}`).join('; ')}`,
      `Estructura: ${plan.storyStructure.map(beat => beat.turningPoint).join(' → ')}`,
    ].join('\n\n')
    useComicStore.getState().patchProject({
      characters,
      director: {
        planId: plan.id,
        provider,
        imageModel,
        input: {
          useGlobalProfile: true,
          premise: project.synopsis || project.title,
          storyContext,
          productionMode: 'comic',
          pageCount: pages.length,
          language: project.language,
          format: project.format.preset,
          panelsPerPage: Math.max(1, pages[0]?.panels.length || 4),
          genre: 'Comedy',
          tone: 'Warm',
          audience: 'General',
          artStyle: project.style.name,
          worldContext: `Universo visual de “${project.title}”. Mantener época, localizaciones, escala y utilería coherentes entre páginas.`,
          forbiddenElements: 'No cambiar identidades ni vestuario. No añadir texto, cuadrículas, marcos, logos o marcas de agua dentro de la ilustración.',
          dialogueDensity: 'medium',
          provider,
          imageModel,
          characters,
          ending: plan.storyStructure.at(-1)?.turningPoint,
        },
        plan,
        completedPanelIds: [],
        failedPanelIds: [],
        panelJobs: {},
        scriptVersion: 1,
        scriptApprovedAt: new Date().toISOString(),
      },
    })
  }
  if (!useComicStore.getState().project.director) {
    throw new Error(i18n.t('comics:actionErrors.noDirectorPlan'))
  }
  const current = useComicStore.getState().project.director!
  if (current.factualBiography && !current.biographyReviewedAt && !action.biographyReview) {
    throw new Error(i18n.t('comics:actionErrors.biographyBlocked'))
  }
  if (action.biographyReview && !current.biographyReviewedAt) {
    useComicStore.getState().patchProject({
      director: { ...current, biographyReviewedAt: new Date().toISOString() },
    })
  }
  if (action.imageProvider !== 'keep' || action.imageModel) {
    const latest = useComicStore.getState().project.director!
    const provider = action.imageProvider === 'keep' ? latest.provider : action.imageProvider
    const imageModel = action.imageModel || (provider === 'minimax' ? 'image-01' : latest.imageModel)
    useComicStore.getState().patchProject({ director: { ...latest, provider, imageModel, input: { ...latest.input, provider, imageModel } } })
  }
  const pages = action.pilot ? [1] : (action.pages || [])
  const result = await generateDirectorArtwork({
    scope: action.scope || 'missing',
    pages: pages.length ? pages : undefined,
    force: action.scope === 'all',
    onProgress: (message, current, total) => {
      onProgress?.(`${message} (${current}/${total})`)
    },
  })
  const project = useComicStore.getState().project
  const provider = project.director?.provider
  const providerLabel = provider === 'minimax' ? 'MiniMax image-01' : i18n.t('comics:replies.configuredLocalProvider')
  if (!result.total) {
    return comicResult(project, i18n.t('comics:replies.alreadyDrawn'), {
      status: 'completed', generated: 0, failed: 0, cancelled: false,
    })
  }
  if (result.cancelled) {
    return comicResult(
      project,
      i18n.t('comics:replies.cancelled', { generated: result.generated, failed: result.failed }),
      {
        status: result.generated > 0 ? 'partial' : 'failed',
        generated: result.generated,
        failed: result.failed,
        cancelled: true,
      },
    )
  }
  if (result.failed) {
    return comicResult(
      project,
      i18n.t('comics:replies.partial', { generated: result.generated, failed: result.failed, provider: providerLabel }),
      {
        status: result.generated > 0 ? 'partial' : 'failed',
        generated: result.generated,
        failed: result.failed,
        cancelled: false,
      },
    )
  }
  return comicResult(
    project,
    i18n.t('comics:replies.drawn', { generated: result.generated, provider: providerLabel }),
    { status: 'completed', generated: result.generated, failed: 0, cancelled: false },
  )
}

export async function generateComicPanelArtwork(
  pageNumber: number,
  panelNumber: number,
  onProgress?: (message: string) => void,
): Promise<CommandResult> {
  const [{ useComicStore }, { generateDirectorArtwork }] = await Promise.all([
    import('./store'),
    import('./generateArtwork'),
  ])
  if (!useComicStore.getState().project.director) {
    throw new Error(i18n.t('comics:actionErrors.regenerateNeedsPlan'))
  }
  const result = await generateDirectorArtwork({
    force: true,
    target: { pageNumber, panelNumber },
    onProgress: (message, current, total) => onProgress?.(`${message} (${current}/${total})`),
  })
  if (result.failed) throw new Error(i18n.t('comics:actionErrors.regenerateFailed', { panel: panelNumber, page: pageNumber }))
  return comicResult(
    useComicStore.getState().project,
    i18n.t('comics:replies.regenerated', {
      panel: panelNumber,
      page: pageNumber,
      generated: result.generated,
      total: result.total,
    }),
  )
}
