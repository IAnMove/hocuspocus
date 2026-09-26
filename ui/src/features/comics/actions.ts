import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
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
  const characters = (action.characters.length ? action.characters : [{
    name: 'Protagonist',
    role: 'Protagonist',
    personality: '',
    desire: '',
    flaw: '',
    appearance: 'Clear, recognizable silhouette',
    voice: '',
  }]).map((character, index) => ({
    id: comicId('character'),
    name: character.name || `Character ${index + 1}`,
    description: character.appearance || character.role || character.name,
    role: character.role || (index ? 'Secundario' : 'Protagonist'),
    personality: character.personality,
    motivation: character.desire,
    voice: character.voice,
    wardrobe: character.appearance || 'Fixed, recognizable wardrobe throughout the comic.',
    visualNotes: [character.appearance, action.styleName, 'Constant silhouette, scale and palette.'].filter(Boolean).join('. '),
    negativePrompt: 'inconsistent face, changed wardrobe, duplicate character, extra limbs, unreadable silhouette',
    referenceAssetIds: [],
    locked: false,
  }))
  const panels = action.panels.length ? action.panels : [
    { caption: action.synopsis || action.title, dialogue: '', sfx: '', scene: action.synopsis },
  ]
  const requestedPages = action.pages.length ? action.pages : [{ title: 'Page 1', stage: '', panels }]
  const allPanels = requestedPages.flatMap(page => page.panels)
  const languageIntent = mergeLanguageIntent(undefined, action.languageIntent, {
    contentLanguage: action.language || 'English',
    technicalPromptLanguage: 'en',
  })
  const ending = allPanels.at(-1)?.dialogue
    || allPanels.at(-1)?.caption
    || `The conflict of “${action.title}” resolves with a clear visual consequence.`
  const castBible = characters.map(character => [
    `${character.name} (${character.role || 'personaje'})`,
    character.description,
    character.personality,
    character.motivation,
  ].filter(Boolean).join(': ')).join('\n')
  const storyContext = [
    `Premise: ${action.synopsis || action.title}`,
    `Characters:\n${castBible}`,
    `Progression: ${requestedPages.map((page, index) => `${index + 1}. ${page.title}: ${page.stage || page.panels[0]?.scene || page.panels[0]?.caption}`).join(' → ')}`,
    `Ending: ${ending}`,
  ].join('\n\n')
  const worldContext = [
    `Visual universe of “${action.title}”.`,
    action.synopsis,
    `Keep locations, period, scale and props consistent across ${requestedPages.length} pages and ${allPanels.length} panels.`,
  ].filter(Boolean).join(' ')
  const forbiddenElements = [
    'Do not change the characters\' design, apparent age, palette or wardrobe between panels.',
    'Do not add text, speech balloons, frames, grids, logos or watermarks inside the generated images.',
    'Do not duplicate characters or introduce elements foreign to the scene.',
  ].join(' ')
  const planId = comicId('plan')
  const plan = {
    version: 1 as const,
    id: planId,
    title: action.title,
    logline: action.synopsis,
    synopsis: action.synopsis || action.title,
    language: languageIntent.contentLanguage || action.language || 'English',
    styleBible: action.styleName || 'Clean comic strip, 4 panels',
    characters,
    storyStructure: requestedPages.map((page, pageIndex) => ({
      pageNumber: pageIndex + 1, stage: page.stage || page.title,
      goal: `Clearly depict the stage “${page.title}”.`,
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
          narrativeRole: `${page.title} · panel ${index + 1}`,
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
          continuityNotes: `Keep identity, wardrobe, palette, lighting and spatial axis consistent with panel ${Math.max(1, index)}.`,
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
      language: languageIntent.contentLanguage || action.language || 'English',
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
    throw new Error(`The saved comic has ${stored.pages.length} pages and ${storedPanels} panels; you asked for ${requestedPages.length} pages and ${allPanels.length} panels.`)
  }
  return comicResult(
    project,
    `I created “${project.title}” from scratch with ${requestedPages.length} pages, ${characters.length} characters and ${allPanels.length} panels. Comic Director will use ${provider === 'minimax' ? 'MiniMax image-01' : imageModel || 'the selected local model'}. I have not generated images yet.`,
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
    const characters = (project.characters.length ? project.characters : [{
      id: comicId('character'),
      name: 'Protagonist',
      description: 'Clear silhouette',
      locked: false,
    }]).map(character => ({
      ...character,
      role: character.role || 'Main character',
      personality: character.personality || 'Expressive and consistent with the comic\'s tone.',
      motivation: character.motivation || project.synopsis || 'Resolve the story\'s conflict.',
      voice: character.voice || 'Short, clear, distinctive voice.',
      wardrobe: character.wardrobe || character.description || 'Fixed, recognizable wardrobe.',
      visualNotes: character.visualNotes || `${character.description}. Constant silhouette, scale and palette.`,
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
            narrativeRole: `Panel ${index + 1}`,
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
            continuityNotes: `Keep identity, wardrobe, palette and spatial axis consistent with panel ${Math.max(1, index)}.`,
          }
        }),
      }
    })
    if (!pages.some(page => page.panels.length)) {
      throw new Error('The open comic has no panels to draw.')
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
        stage: index === 0 ? 'Setup and complication' : `Development ${index + 1}`,
        goal: project.synopsis || `Advance “${project.title}”.`,
        turningPoint: page.panels.at(-1)?.dialogue.at(-1)?.text
          || page.panels.at(-1)?.captions.at(-1)
          || `Close the beat of page ${page.pageNumber}.`,
      })),
      pages,
    }
    const storyContext = [
      `Premise: ${project.synopsis || project.title}`,
      `Personajes: ${characters.map(character => `${character.name}: ${character.description}`).join('; ')}`,
      `Structure: ${plan.storyStructure.map(beat => beat.turningPoint).join(' → ')}`,
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
          worldContext: `Visual universe of “${project.title}”. Keep period, locations, scale and props consistent between pages.`,
          forbiddenElements: 'Do not change identities or wardrobe. Do not add text, grids, frames, logos or watermarks inside the illustration.',
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
    throw new Error('No comic with a Director plan is open. First ask for an example comic or create one with a topic.')
  }
  const current = useComicStore.getState().project.director!
  if (current.factualBiography && !current.biographyReviewedAt && !action.biographyReview) {
    throw new Error('This comic is a factual biography. Confirm facts, inferences and dramatization (biography_review=true) before drawing; I won\'t invent relatives, quotes or events.')
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
  const providerLabel = provider === 'minimax' ? 'MiniMax image-01' : 'the configured local provider'
  if (!result.total) {
    return comicResult(project, 'Every panel of this comic already had artwork.', {
      status: 'completed', generated: 0, failed: 0, cancelled: false,
    })
  }
  if (result.cancelled) {
    return comicResult(
      project,
      `I cancelled the batch with ${result.generated} panels finished and ${result.failed} failed; nothing already drawn was lost.`,
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
      `I drew ${result.generated} panels with ${providerLabel} and ${result.failed} failed. I can resume from the first pending one or retry the failed ones.`,
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
    `I drew ${result.generated} panels with ${providerLabel}. They appear inside each frame when finished.`,
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
    throw new Error('The open comic has no Director plan. Create the full draft first before regenerating a panel.')
  }
  const result = await generateDirectorArtwork({
    force: true,
    target: { pageNumber, panelNumber },
    onProgress: (message, current, total) => onProgress?.(`${message} (${current}/${total})`),
  })
  if (result.failed) throw new Error(`I couldn't regenerate panel ${panelNumber} of page ${pageNumber}.`)
  return comicResult(
    useComicStore.getState().project,
    `I regenerated only panel ${panelNumber} of page ${pageNumber}; the other images are untouched (${result.generated}/${result.total}).`,
  )
}
