import type {
  ComicElement,
  ComicPage,
  ComicPanelElement,
  ComicPlan,
  ComicProject,
  ComicTextElement,
} from './types'

function randomIdPart(): string {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID().slice(0, 8)
  }
  if (typeof cryptoApi?.getRandomValues === 'function') {
    const values = new Uint32Array(2)
    cryptoApi.getRandomValues(values)
    return Array.from(values, value => value.toString(36)).join('').slice(0, 12)
  }
  return `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`.slice(0, 12)
}

/** IDs must also work on LAN HTTP origins, where randomUUID is unavailable. */
export const comicId = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${randomIdPart()}`

export const COMIC_FORMATS = {
  a4: { width: 800, height: 1131, dpi: 300, label: 'A4 portrait' },
  'us-comic': { width: 800, height: 1231, dpi: 300, label: 'US Comic' },
  square: { width: 1080, height: 1080, dpi: 144, label: 'Square' },
  webtoon: { width: 800, height: 2400, dpi: 144, label: 'Webtoon' },
} as const

export function repairMojibake(text: string): string {
  if (!/[ÃÂâ]/.test(text)) return text
  const codes = Array.from(text, character => character.charCodeAt(0))
  if (codes.some(code => code > 255)) return text
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(codes))
  } catch {
    return text
  }
}

export function repairComicText<T>(value: T): T {
  if (typeof value === 'string') return repairMojibake(value) as T
  if (Array.isArray(value)) return value.map(item => repairComicText(item)) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, repairComicText(item)]),
    ) as T
  }
  return value
}

const copyKey = (value: string) => value.trim().replace(/\s+/g, ' ').toLocaleLowerCase()

function compactUnique<T>(
  values: T[],
  text: (value: T) => string,
  limit: number,
  seen = new Set<string>(),
): T[] {
  if (limit <= 0) return []
  const compacted: T[] = []
  for (const value of values) {
    const key = copyKey(text(value))
    if (!key || seen.has(key)) continue
    seen.add(key)
    compacted.push(value)
    if (compacted.length >= limit) break
  }
  return compacted
}

/** A generated panel must leave most of its artwork visible. */
function compactPanelCopy(
  panel: ComicPlan['pages'][number]['panels'][number],
  panelCount = 1,
  panelIndex = 0,
  layoutHint: ComicPlan['pages'][number]['layoutHint'] = 'grid',
) {
  const seen = new Set<string>()
  const isLargePanel = panelCount <= 4 || (layoutHint === 'dynamic' && panelIndex === 0)
  const maxElements = isLargePanel ? 2 : 1
  const captions = compactUnique(
    Array.isArray(panel.captions) ? panel.captions : [],
    value => value,
    1,
    seen,
  )
  const dialogue = compactUnique(
    Array.isArray(panel.dialogue) ? panel.dialogue : [],
    value => value.text,
    Math.max(0, maxElements - captions.length),
    seen,
  )
  const soundEffects = compactUnique(
    Array.isArray(panel.soundEffects) ? panel.soundEffects : [],
    value => value,
    Math.max(0, maxElements - captions.length - dialogue.length),
    seen,
  )
  return { captions, dialogue, soundEffects }
}

/** Accept a structurally valid plan even when an LLM response was repaired
 *  after truncation and its final panel omitted trailing collection fields. */
export function normalizeComicPlan(
  plan: ComicPlan,
  dialogueDensity: 'low' | 'medium' | 'high' = 'medium',
): ComicPlan {
  const repaired = repairComicText(plan)
  const normalized: ComicPlan = {
    ...repaired,
    characters: (Array.isArray(repaired.characters) ? repaired.characters : []).map(character => ({
      ...character,
      referenceAssetIds: Array.from(new Set([
        ...(Array.isArray(character.referenceAssetIds) ? character.referenceAssetIds : []),
        ...(character.referenceAssetId ? [character.referenceAssetId] : []),
      ])),
    })),
    pages: (Array.isArray(repaired.pages) ? repaired.pages : []).map((page, pageIndex) => ({
      ...page,
      pageNumber: Number(page.pageNumber) || pageIndex + 1,
      layoutHint: page.layoutHint === 'dynamic' ? 'dynamic' as const : 'grid' as const,
      panels: (Array.isArray(page.panels) ? page.panels : []).map((panel, panelIndex) => {
        const copy = compactPanelCopy(panel, page.panels.length, panelIndex, page.layoutHint)
        return {
          ...panel,
          id: panel.id || `p${pageIndex + 1}-panel${panelIndex + 1}`,
          order: Number(panel.order) || panelIndex + 1,
          narrativeRole: panel.narrativeRole || 'Story beat',
          sceneDescription: panel.sceneDescription || panel.narrativeRole || 'Comic panel',
          imagePrompt: panel.imagePrompt || panel.sceneDescription || 'Comic panel',
          characters: Array.isArray(panel.characters) ? panel.characters : [],
          framing: panel.framing || 'Medium shot',
          dialogue: copy.dialogue,
          captions: copy.captions,
          soundEffects: copy.soundEffects,
          continuityNotes: panel.continuityNotes || '',
        }
      }),
    })),
  }
  const ratio = { low: 0.3, medium: 0.55, high: 0.8 }[dialogueDensity]
  normalized.pages.forEach(page => {
    const withText = page.panels
      .map((panel, index) => ({ panel, index }))
      .filter(({ panel }) =>
        panel.captions.length + panel.dialogue.length + panel.soundEffects.length > 0)
    const budget = Math.max(1, Math.ceil(page.panels.length * ratio))
    if (withText.length <= budget) return
    const keep = new Set<number>()
    for (let position = 0; position < budget; position += 1) {
      const sourceIndex = budget === 1
        ? 0
        : Math.round(position * (withText.length - 1) / (budget - 1))
      keep.add(withText[sourceIndex].index)
    }
    page.panels.forEach((panel, index) => {
      if (keep.has(index)) return
      panel.captions = []
      panel.dialogue = []
      panel.soundEffects = []
    })
  })
  return normalized
}

export function createComicPage(width = 800, height = 1131): ComicPage {
  return { id: comicId('page'), width, height, background: '#ffffff', elements: [] }
}

export function createComicProject(): ComicProject {
  const now = new Date().toISOString()
  return {
    version: 2,
    id: comicId('comic'),
    title: 'Untitled comic',
    synopsis: '',
    language: 'English',
    format: { preset: 'a4', width: 800, height: 1131, dpi: 300 },
    style: {
      name: 'Modern comic',
      promptSuffix: 'single full-bleed comic-panel illustration, expressive ink, clean composition',
      fontFamily: '"Comic Sans MS", "Trebuchet MS", sans-serif',
      palette: ['#ffffff', '#111111', '#facc15', '#ef4444'],
    },
    pageNumbering: { style: 'plain' },
    characters: [],
    translationGlossary: [],
    pages: [createComicPage()],
    assets: {},
    createdAt: now,
    updatedAt: now,
  }
}

const PANEL_MARGIN = 28
const PANEL_GAP = 14

export function panelsForCount(page: ComicPage, count: number): ComicPanelElement[] {
  const columns = count === 1 ? 1 : count <= 4 ? 2 : count <= 6 ? 2 : 3
  const rows = Math.ceil(count / columns)
  const usableH = page.height - PANEL_MARGIN * 2 - PANEL_GAP * (rows - 1)
  const panelH = usableH / rows
  return Array.from({ length: count }, (_, index) => {
    const row = Math.floor(index / columns)
    const inLastRow = row === rows - 1 ? count - row * columns : columns
    const rowWidth = page.width - PANEL_MARGIN * 2 - PANEL_GAP * (inLastRow - 1)
    const currentW = rowWidth / inLastRow
    const col = index - row * columns
    return {
      id: comicId('panel'),
      type: 'panel',
      x: PANEL_MARGIN + col * (currentW + PANEL_GAP),
      y: PANEL_MARGIN + row * (panelH + PANEL_GAP),
      width: currentW,
      height: panelH,
      rotation: 0,
      zIndex: index + 1,
      parentId: null,
      visible: true,
      background: '#ffffff',
      borderColor: '#111111',
      borderWidth: 4,
      borderRadius: 0,
    }
  })
}

function customPanel(
  x: number,
  y: number,
  width: number,
  height: number,
  index: number,
): ComicPanelElement {
  return {
    id: comicId('panel'),
    type: 'panel',
    x: Math.round(x),
    y: Math.round(y),
    width: Math.round(width),
    height: Math.round(height),
    rotation: 0,
    zIndex: index + 1,
    parentId: null,
    visible: true,
    background: '#ffffff',
    borderColor: '#111111',
    borderWidth: 4,
    borderRadius: 0,
  }
}

/** Cinematic alternatives that preserve the requested panel count. */
export function dynamicPanelsForCount(page: ComicPage, count: number): ComicPanelElement[] {
  if (![3, 4, 6, 9].includes(count)) return panelsForCount(page, count)
  const margin = PANEL_MARGIN
  const gap = PANEL_GAP
  const width = page.width - margin * 2
  const height = page.height - margin * 2
  const panels: ComicPanelElement[] = []
  const add = (x: number, y: number, w: number, h: number) => {
    panels.push(customPanel(x, y, w, h, panels.length))
  }
  if (count === 3) {
    const heroH = (height - gap) * .58
    const lowerH = height - gap - heroH
    add(margin, margin, width, heroH)
    add(margin, margin + heroH + gap, (width - gap) / 2, lowerH)
    add(margin + (width + gap) / 2, margin + heroH + gap, (width - gap) / 2, lowerH)
  } else if (count === 4) {
    const heroH = (height - gap) * .55
    const lowerH = height - gap - heroH
    add(margin, margin, width, heroH)
    const smallW = (width - gap * 2) / 3
    for (let column = 0; column < 3; column++) {
      add(margin + column * (smallW + gap), margin + heroH + gap, smallW, lowerH)
    }
  } else if (count === 6) {
    const firstH = (height - gap * 2) * .4
    const secondH = (height - gap * 2) * .27
    const thirdH = height - gap * 2 - firstH - secondH
    add(margin, margin, width, firstH)
    add(margin, margin + firstH + gap, (width - gap) / 2, secondH)
    add(margin + (width + gap) / 2, margin + firstH + gap, (width - gap) / 2, secondH)
    const smallW = (width - gap * 2) / 3
    for (let column = 0; column < 3; column++) {
      add(margin + column * (smallW + gap), margin + firstH + secondH + gap * 2, smallW, thirdH)
    }
  } else {
    const rowH = (height - gap * 2) / 3
    const columnW = (width - gap * 2) / 3
    add(margin, margin, columnW * 2 + gap, rowH)
    const stackedH = (rowH - gap) / 2
    add(margin + (columnW + gap) * 2, margin, columnW, stackedH)
    add(margin + (columnW + gap) * 2, margin + stackedH + gap, columnW, stackedH)
    for (let row = 1; row < 3; row++) {
      for (let column = 0; column < 3; column++) {
        add(
          margin + column * (columnW + gap),
          margin + row * (rowH + gap),
          columnW,
          rowH,
        )
      }
    }
  }
  return panels
}

export function textElement(
  panel: ComicPanelElement,
  content: string,
  bubble: ComicTextElement['bubble'],
  order: number,
): ComicTextElement {
  const compact = panel.width < 280 || panel.height < 260
  const width = Math.max(110, panel.width * (compact ? 0.72 : 0.66))
  const height = Math.max(compact ? 46 : 60, Math.min(compact ? 92 : 126, 40 + content.length * 0.34))
  const baseSize = compact ? (bubble === 'caption' ? 14 : 15) : (bubble === 'caption' ? 17 : 19)
  const fontSize = content.length > 90 ? baseSize - 3 : content.length > 58 ? baseSize - 2 : baseSize
  return {
    id: comicId('text'),
    type: 'text',
    parentId: panel.id,
    x: bubble === 'caption'
      ? panel.width * 0.05
      : panel.width - width - panel.width * 0.05,
    y: bubble === 'caption'
      ? 10 + order * (height + 8)
      : panel.height - height - 14 - order * (height + 8),
    width,
    height,
    rotation: 0,
    zIndex: 20 + order,
    visible: true,
    content,
    fontSize,
    fontFamily: '"Comic Sans MS", "Trebuchet MS", sans-serif',
    color: '#111111',
    bold: false,
    italic: false,
    align: 'center',
    bubble,
    bubbleBackground: bubble === 'caption' ? '#fff4a3' : '#ffffff',
    bubbleStrokeColor: '#111111',
    bubbleStrokeWidth: 3,
  }
}

export function projectFromPlan(plan: ComicPlan, base?: ComicProject): ComicProject {
  plan = normalizeComicPlan(plan, base?.director?.input.dialogueDensity)
  const project = base ?? createComicProject()
  const pages = plan.pages.map(planPage => {
    const page = createComicPage(project.format.width, project.format.height)
    const panels = planPage.layoutHint === 'dynamic'
      ? dynamicPanelsForCount(page, Math.max(1, planPage.panels.length))
      : panelsForCount(page, Math.max(1, planPage.panels.length))
    const elements: ComicElement[] = [...panels]
    planPage.panels.forEach((planned, index) => {
      const panel = panels[index]
      planned.captions.forEach((caption, i) => elements.push(textElement(panel, caption, 'caption', i)))
      planned.dialogue.forEach((dialogue, i) => elements.push(textElement(panel, dialogue.text, dialogue.bubbleType, i)))
      planned.soundEffects.forEach((sfx, i) => {
        const el = textElement(panel, sfx, 'none', i)
        el.fontSize = 34
        el.bold = true
        el.color = '#facc15'
        el.bubbleStrokeWidth = 0
        el.x = panel.width * 0.2
        el.y = panel.height * 0.45 + i * 50
        elements.push(el)
      })
    })
    return { ...page, elements }
  })
  return {
    ...project,
    title: plan.title,
    synopsis: plan.synopsis,
    language: plan.language,
    characters: plan.characters,
    pages,
    updatedAt: new Date().toISOString(),
  }
}

/** Replace generated copy with the compact, readable version from the Director plan.
 *  Artwork, panels and unrelated page elements are preserved. */
export function simplifyDirectorText(project: ComicProject): ComicProject {
  if (!project.director) return project
  const plan = normalizeComicPlan(
    project.director.plan,
    project.director.input.dialogueDensity,
  )
  const usedAssetIds = new Set(
    project.pages.flatMap(page => page.elements)
      .filter((element): element is Extract<ComicElement, { type: 'image' }> => element.type === 'image')
      .map(element => element.assetId),
  )
  const unusedGeneratedAssets = Object.values(project.assets).filter(asset =>
    !usedAssetIds.has(asset.id) &&
    (asset.kind === 'minimax' || asset.kind === 'local' || asset.kind === 'maestro-output'))
  let unusedAssetIndex = 0
  const pages = plan.pages.map((planPage, pageIndex) => {
    const existingPage = project.pages[pageIndex]
    const page = existingPage ?? createComicPage(project.format.width, project.format.height)
    const panels = existingPage
      ? page.elements
      .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((a, b) => a.zIndex - b.zIndex)
      : panelsForCount(page, Math.max(1, planPage.panels.length))
    const panelIds = new Set(panels.map(panel => panel.id))
    const elements = existingPage
      ? page.elements.filter(
        element => element.type !== 'text' || !element.parentId || !panelIds.has(element.parentId),
      )
      : [...panels] as ComicElement[]
    planPage.panels.forEach((planned, panelIndex) => {
      const panel = panels[panelIndex]
      if (!panel) return
      planned.captions.forEach((caption, index) => {
        elements.push(textElement(panel, caption, 'caption', index))
      })
      planned.dialogue.forEach((dialogue, index) => {
        elements.push(textElement(panel, dialogue.text, dialogue.bubbleType, index))
      })
      planned.soundEffects.forEach((soundEffect, index) => {
        const element = textElement(panel, soundEffect, 'none', index)
        element.fontSize = 30
        element.bold = true
        element.color = '#facc15'
        element.bubbleStrokeWidth = 0
        element.x = panel.width * 0.2
        element.y = panel.height * 0.45
        elements.push(element)
      })
      if (!existingPage && project.director!.completedPanelIds.includes(planned.id)) {
        const asset = unusedGeneratedAssets[unusedAssetIndex++]
        if (asset) {
          elements.push({
            id: comicId('image'),
            type: 'image',
            assetId: asset.id,
            parentId: panel.id,
            x: 0,
            y: 0,
            width: panel.width,
            height: panel.height,
            rotation: 0,
            zIndex: 2,
            objectFit: 'cover',
            filter: 'none',
            opacity: 1,
            visible: true,
          })
        }
      }
    })
    return { ...page, elements }
  })
  pages.push(...project.pages.slice(plan.pages.length))
  return {
    ...project,
    pages,
    director: { ...project.director, plan },
    updatedAt: new Date().toISOString(),
  }
}

/** Capture the text currently visible on the canvas so manual edits are never lost
 *  when the LLM rewrites or translates lettering. */
export function planWithCanvasText(project: ComicProject): ComicPlan | null {
  if (!project.director) return null
  const plan = structuredClone(project.director.plan)
  plan.pages.forEach((planPage, pageIndex) => {
    const page = project.pages[pageIndex]
    if (!page) return
    const panels = page.elements
      .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((a, b) => a.zIndex - b.zIndex)
    planPage.panels.forEach((planned, panelIndex) => {
      const panel = panels[panelIndex]
      if (!panel) return
      const text = page.elements
        .filter((element): element is ComicTextElement =>
          element.type === 'text' && element.parentId === panel.id && element.visible !== false)
        .sort((a, b) => a.zIndex - b.zIndex)
      planned.captions = text.filter(element => element.bubble === 'caption').map(element => element.content)
      planned.soundEffects = text.filter(element => element.bubble === 'none').map(element => element.content)
      const existingDialogue = planned.dialogue
      planned.dialogue = text
        .filter(element => element.bubble !== 'caption' && element.bubble !== 'none')
        .map((element, dialogueIndex) => ({
          speakerId: existingDialogue[dialogueIndex]?.speakerId,
          text: element.content,
          bubbleType: element.bubble === 'scream' || element.bubble === 'thought'
            ? element.bubble
            : 'speech',
        }))
    })
  })
  return plan
}

/** Reflow alternate pages while retaining their attached artwork and plan IDs. */
export function varyDirectorLayouts(project: ComicProject): ComicProject {
  if (!project.director) return project
  const plan = structuredClone(project.director.plan)
  const pages = project.pages.map((page, pageIndex) => {
    const plannedPage = plan.pages[pageIndex]
    if (!plannedPage) return page
    const useDynamic = pageIndex % 2 === 1 && [3, 4, 6, 9].includes(plannedPage.panels.length)
    plannedPage.layoutHint = useDynamic ? 'dynamic' : 'grid'
    const templates = useDynamic
      ? dynamicPanelsForCount(page, plannedPage.panels.length)
      : panelsForCount(page, plannedPage.panels.length)
    const panels = page.elements
      .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((a, b) => a.zIndex - b.zIndex)
    const geometry = new Map(panels.map((panel, index) => [panel.id, templates[index]]))
    return {
      ...page,
      elements: page.elements.map(element => {
        if (element.type === 'panel' && !element.parentId) {
          const template = geometry.get(element.id)
          return template ? {
            ...element,
            x: template.x,
            y: template.y,
            width: template.width,
            height: template.height,
          } : element
        }
        if (element.type === 'image' && element.parentId) {
          const template = geometry.get(element.parentId)
          return template ? { ...element, x: 0, y: 0, width: template.width, height: template.height } : element
        }
        return element
      }),
    }
  })
  return simplifyDirectorText({
    ...project,
    pages,
    director: { ...project.director, plan },
  })
}

export function normalizeComicProject(raw: unknown): ComicProject {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid comic project')
  const doc = raw as Record<string, unknown>
  if (doc.version === 2 && Array.isArray(doc.pages)) {
    const project = repairComicText(doc as unknown as ComicProject)
    project.characters = (Array.isArray(project.characters) ? project.characters : []).map(character => ({
      ...character,
      referenceAssetIds: Array.from(new Set([
        ...(Array.isArray(character.referenceAssetIds) ? character.referenceAssetIds : []),
        ...(character.referenceAssetId ? [character.referenceAssetId] : []),
      ])),
    }))
    project.translationGlossary = Array.isArray(project.translationGlossary)
      ? project.translationGlossary
      : []
    if (project.director) {
      project.director.scriptVersion = Number(project.director.scriptVersion || 1)
      project.director.input.writingProvider = project.director.input.writingProvider || 'maestro'
      project.director.input.writingModel = project.director.input.writingModel || 'deepseek-chat'
      project.director.input.writingBaseUrl = project.director.input.writingBaseUrl || 'https://api.deepseek.com'
    }
    return project
  }
  if (doc.version !== 1 || !Array.isArray(doc.pages)) throw new Error('Unsupported comic project')

  const migrated = createComicProject()
  const assets: ComicProject['assets'] = {}
  const pages = (doc.pages as Array<Record<string, unknown>>).map(oldPage => ({
    id: String(oldPage.id || comicId('page')),
    width: Number(oldPage.width || 800),
    height: Number(oldPage.height || 1131),
    background: String(oldPage.background || '#ffffff'),
    elements: ((oldPage.elements as Array<Record<string, unknown>>) || []).map(rawEl => {
      const el = { ...rawEl } as Record<string, unknown>
      if (el.type === 'image' && typeof el.src === 'string') {
        const assetId = comicId('asset')
        assets[assetId] = {
          id: assetId,
          name: `Imported image ${Object.keys(assets).length + 1}`,
          kind: 'upload',
          source: el.src,
          prompt: typeof el.prompt === 'string' ? el.prompt : undefined,
          createdAt: new Date().toISOString(),
          missing: el.src.startsWith('blob:'),
        }
        el.assetId = assetId
        delete el.src
      }
      return {
        rotation: 0,
        visible: true,
        ...el,
      } as unknown as ComicElement
    }),
  }))
  return {
    ...migrated,
    title: String(doc.title || 'Imported comic'),
    pages,
    assets,
  }
}
