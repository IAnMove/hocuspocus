import type {
  ComicElement,
  ComicPage,
  ComicPanelElement,
  ComicPlan,
  ComicPlanPanel,
  ComicProvenance,
  ComicProject,
  ComicTextElement,
  ComicVideoOverrideField,
} from './types'
import { normalizeLanguageIntent } from '../../lib/languageIntent'

const COMIC_VIDEO_OVERRIDE_FIELDS: readonly ComicVideoOverrideField[] = [
  'included',
  'order',
  'action',
  'renderer',
  'fit',
  'motion_mode',
  'motion_level',
  'duration',
  'camera',
  'video_prompt',
  'seed',
  'end_frame',
  'test_selected',
]

export function mergeComicVideoOverrideFields(
  current: readonly ComicVideoOverrideField[] | undefined,
  add: readonly ComicVideoOverrideField[] = [],
  remove: readonly ComicVideoOverrideField[] = [],
): ComicVideoOverrideField[] {
  const fields = new Set<ComicVideoOverrideField>(current || [])
  remove.forEach(field => fields.delete(field))
  add.forEach(field => fields.add(field))
  return COMIC_VIDEO_OVERRIDE_FIELDS.filter(field => fields.has(field))
}

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

const copyKey = (value: unknown) =>
  String(value ?? '').trim().replace(/\s+/g, ' ').toLocaleLowerCase()

function compactUnique<T>(
  values: T[],
  text: (value: T) => unknown,
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
    (Array.isArray(panel.soundEffects) ? panel.soundEffects : [])
      .filter(value => !isIncompleteSoundEffect(value)),
    value => value,
    Math.max(0, maxElements - captions.length - dialogue.length),
    seen,
  )
  return { captions, dialogue, soundEffects }
}

/** A trailing dash is how truncated LLM lettering commonly leaks into a plan.
 * It is not useful reader-facing copy and should not become a floating glyph. */
function isIncompleteSoundEffect(value: unknown): boolean {
  const text = String(value ?? '').trim()
  return !text || !/[\p{L}\p{N}]/u.test(text) || /[-–—]\s*$/u.test(text)
}

/** Accept a structurally valid plan even when an LLM response was repaired
 *  after truncation and its final panel omitted trailing collection fields. */
export function normalizeComicPlan(
  plan: ComicPlan,
  dialogueDensity: 'low' | 'medium' | 'high' = 'medium',
): ComicPlan {
  const repaired = repairComicText(plan)
  const storyStructure = (Array.isArray(repaired.storyStructure)
    ? repaired.storyStructure
    : []).map((beat, index) => ({
      ...beat,
      pageNumber: Number(beat?.pageNumber) || index + 1,
      stage: String(beat?.stage || ''),
      goal: String(beat?.goal || ''),
      turningPoint: String(beat?.turningPoint || ''),
    }))
  const normalized: ComicPlan = {
    ...repaired,
    version: 1,
    id: String(repaired.id || comicId('comic-plan')),
    title: String(repaired.title || 'Untitled comic'),
    logline: String(repaired.logline || ''),
    synopsis: String(repaired.synopsis || ''),
    language: String(repaired.language || 'English'),
    styleBible: String(repaired.styleBible || ''),
    storyStructure,
    characters: (Array.isArray(repaired.characters) ? repaired.characters : []).map(character => ({
      ...character,
      id: String(character?.id || comicId('character')),
      name: String(character?.name || 'Unnamed character'),
      description: String(character?.description || ''),
      locked: Boolean(character?.locked),
      referenceAssetIds: Array.from(new Set([
        ...(Array.isArray(character.referenceAssetIds) ? character.referenceAssetIds : []),
        ...(character.referenceAssetId ? [character.referenceAssetId] : []),
      ].map(value => String(value)).filter(Boolean))),
    })),
    pages: (Array.isArray(repaired.pages) ? repaired.pages : []).map((page, pageIndex) => ({
      ...page,
      pageNumber: Number(page.pageNumber) || pageIndex + 1,
      layoutHint: page.layoutHint === 'dynamic' ? 'dynamic' as const : 'grid' as const,
      panels: (Array.isArray(page.panels) ? page.panels : []).map((panel, panelIndex) => {
        const safePanel: ComicPlanPanel = {
          ...panel,
          id: String(panel?.id || `p${pageIndex + 1}-panel${panelIndex + 1}`),
          order: Number(panel?.order) || panelIndex + 1,
          narrativeRole: String(panel?.narrativeRole || 'Story beat'),
          sceneDescription: String(
            panel?.sceneDescription || panel?.narrativeRole || 'Comic panel',
          ),
          imagePrompt: String(
            panel?.imagePrompt || panel?.sceneDescription || 'Comic panel',
          ),
          characters: (Array.isArray(panel?.characters) ? panel.characters : [])
            .map(value => String(value))
            .filter(Boolean),
          framing: String(panel?.framing || 'Medium shot'),
          dialogue: (Array.isArray(panel?.dialogue) ? panel.dialogue : [])
            .filter(line => line && typeof line === 'object')
            .map(line => ({
              ...line,
              text: String(line.text || ''),
              bubbleType: line.bubbleType || 'speech',
            }))
            .filter(line => line.text.trim()),
          captions: (Array.isArray(panel?.captions) ? panel.captions : [])
            .map(value => String(value))
            .filter(value => value.trim()),
          soundEffects: (Array.isArray(panel?.soundEffects) ? panel.soundEffects : [])
            .map(value => String(value))
            .filter(value => value.trim()),
          continuityNotes: String(panel?.continuityNotes || ''),
          videoPrompt: String(panel?.videoPrompt || ''),
          videoAction: String(panel?.videoAction || ''),
          durationSeconds: Number.isFinite(Number(panel?.durationSeconds))
            ? Math.max(.8, Math.min(20, Number(panel.durationSeconds)))
            : undefined,
          cameraMove: ['none', 'push-in', 'pull-out', 'pan-left', 'pan-right']
            .includes(String(panel?.cameraMove))
            ? panel.cameraMove
            : undefined,
          videoMotion: ['auto', 'contextual', 'living-still', 'action']
            .includes(String(panel?.videoMotion))
            ? panel.videoMotion
            : undefined,
          videoIncluded: typeof panel?.videoIncluded === 'boolean'
            ? panel.videoIncluded
            : undefined,
          videoOrder: Number.isFinite(Number(panel?.videoOrder))
            ? Math.max(0, Math.floor(Number(panel.videoOrder)))
            : undefined,
          videoRenderer: ['hold', 'parallax', 'cinemagraph', 'ltx']
            .includes(String(panel?.videoRenderer))
            ? panel.videoRenderer
            : undefined,
          videoFit: ['reframe', 'cover', 'contain']
            .includes(String(panel?.videoFit))
            ? panel.videoFit
            : undefined,
          videoMotionLevel: [0, 1, 2, 3].includes(Number(panel?.videoMotionLevel))
            ? Number(panel.videoMotionLevel) as ComicPlanPanel['videoMotionLevel']
            : undefined,
          videoTestSelected: typeof panel?.videoTestSelected === 'boolean'
            ? panel.videoTestSelected
            : undefined,
          videoSeed: Number.isFinite(Number(panel?.videoSeed))
            ? Math.trunc(Number(panel.videoSeed))
            : undefined,
          videoSourcePanelIds: (Array.isArray(panel?.videoSourcePanelIds)
            ? panel.videoSourcePanelIds
            : []
          ).map(value => String(value)).filter(Boolean),
          videoOverrideFields: COMIC_VIDEO_OVERRIDE_FIELDS.filter(field =>
            (Array.isArray(panel?.videoOverrideFields) ? panel.videoOverrideFields : [])
              .includes(field),
          ),
          videoEndFrame: ['auto', 'none', 'next-panel']
            .includes(String(panel?.videoEndFrame))
            ? panel.videoEndFrame
            : panel?.videoTransition === 'cut'
              ? 'none'
              : panel?.videoTransition === 'interpolate'
                ? 'next-panel'
                : panel?.videoTransition === 'auto'
                  ? 'auto'
                  : undefined,
          // Drop the misleading legacy field after translating it so newly
          // saved projects have one unambiguous source of truth.
          videoTransition: undefined,
        }
        const copy = compactPanelCopy(
          safePanel,
          page.panels.length,
          panelIndex,
          page.layoutHint,
        )
        return {
          ...safePanel,
          dialogue: copy.dialogue,
          captions: copy.captions,
          soundEffects: copy.soundEffects,
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
    languageIntent: normalizeLanguageIntent(null, {
      contentLanguage: 'English',
      technicalPromptLanguage: 'en',
    }),
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
  const width = Math.max(110, panel.width * (compact ? 0.8 : 0.72))
  const baseSize = compact ? (bubble === 'caption' ? 14 : 15) : (bubble === 'caption' ? 17 : 19)
  let fontSize = content.length > 90 ? baseSize - 3 : content.length > 58 ? baseSize - 2 : baseSize
  const padding = compact ? 9 : 12
  const availableTextWidth = Math.max(60, width - padding * 2 - 6)
  const wrappedLineCount = (size: number) => {
    const charactersPerLine = Math.max(8, Math.floor(availableTextWidth / (size * 0.54)))
    return content.split('\n').reduce((total, paragraph) => {
      const words = paragraph.trim().split(/\s+/).filter(Boolean)
      if (!words.length) return total + 1
      let lines = 1
      let used = 0
      words.forEach(word => {
        const length = Math.max(1, word.length)
        if (used && used + 1 + length > charactersPerLine) {
          lines += 1
          used = length
        } else {
          used += (used ? 1 : 0) + length
        }
      })
      return total + lines
    }, 0)
  }
  const requiredHeight = (size: number) =>
    Math.ceil(wrappedLineCount(size) * size * 1.12 + padding * 2 + 8)
  const preferredMaxHeight = panel.height * (compact ? 0.48 : 0.42)
  while (fontSize > 10 && requiredHeight(fontSize) > preferredMaxHeight) fontSize -= 1
  const height = Math.min(
    Math.max(40, panel.height - 16),
    Math.max(compact ? 50 : 64, requiredHeight(fontSize)),
  )
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
    letteringType: bubble === 'caption' ? 'caption' : 'dialogue',
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
    bubblePadding: padding,
    autoFit: true,
  }
}

/** Build display lettering with a box sized for its final large font.
 *
 * Generated SFX use an explicit burst container so their contrast does not
 * depend on the underlying artwork. Keeping the geometry here also prevents
 * regenerated effects from sharing one position or clipping large glyphs.
 */
export function soundEffectElement(
  panel: ComicPanelElement,
  content: string,
  order: number,
): ComicTextElement {
  const compact = panel.width < 280 || panel.height < 260
  const fontSize = compact ? 27 : 34
  const padding = compact ? 5 : 7
  const width = Math.min(
    panel.width - 16,
    Math.max(
      panel.width * 0.56,
      Math.min(panel.width * 0.88, content.length * fontSize * 0.64 + padding * 4),
    ),
  )
  const charactersPerLine = Math.max(
    5,
    Math.floor((width - padding * 2) / (fontSize * 0.62)),
  )
  const lineCount = Math.max(1, Math.ceil(content.length / charactersPerLine))
  const height = Math.min(
    panel.height * 0.36,
    Math.max(fontSize * 1.9, lineCount * fontSize * 1.2 + padding * 4),
  )
  const preferredY = panel.height * 0.42 + order * (height + 7)
  return {
    id: comicId('text'),
    type: 'text',
    parentId: panel.id,
    x: Math.max(8, (panel.width - width) / 2),
    y: Math.max(8, Math.min(panel.height - height - 8, preferredY)),
    width,
    height,
    rotation: order % 2 === 0 ? -2 : 2,
    zIndex: 24 + order,
    visible: true,
    letteringType: 'sound-effect',
    content,
    fontSize,
    fontFamily: '"Comic Sans MS", "Trebuchet MS", sans-serif',
    color: '#111111',
    bold: true,
    italic: false,
    align: 'center',
    bubble: 'burst',
    bubbleBackground: '#fff4a3',
    bubbleStrokeColor: '#111111',
    bubbleStrokeWidth: 3,
    bubblePadding: padding * 2,
    bubbleShadow: true,
    autoFit: true,
  }
}

export function projectFromPlan(
  plan: ComicPlan,
  base?: ComicProject,
  productionMode: 'comic' | 'storyboard' = base?.director?.input.productionMode || 'comic',
): ComicProject {
  plan = normalizeComicPlan(plan, base?.director?.input.dialogueDensity)
  const project = base ?? createComicProject()
  const storyboard = productionMode === 'storyboard'
  const pages = plan.pages.map(planPage => {
    const page = createComicPage(project.format.width, project.format.height)
    const panels = storyboard
      ? [customPanel(0, 0, page.width, page.height, 0)].map(panel => ({
          ...panel,
          borderWidth: 0,
        }))
      : planPage.layoutHint === 'dynamic'
        ? dynamicPanelsForCount(page, Math.max(1, planPage.panels.length))
        : panelsForCount(page, Math.max(1, planPage.panels.length))
    const elements: ComicElement[] = [...panels]
    planPage.panels.forEach((planned, index) => {
      const panel = panels[index]
      if (!panel || storyboard) return
      planned.captions.forEach((caption, i) => elements.push(textElement(panel, caption, 'caption', i)))
      planned.dialogue.forEach((dialogue, i) => elements.push(textElement(panel, dialogue.text, dialogue.bubbleType, i)))
      planned.soundEffects.forEach((sfx, i) => elements.push(soundEffectElement(panel, sfx, i)))
    })
    return { ...page, elements }
  })
  return withComicContentLanguage({
    ...project,
    title: plan.title,
    synopsis: plan.synopsis,
    characters: plan.characters,
    pages,
    updatedAt: new Date().toISOString(),
  }, plan.language)
}

export function withComicContentLanguage(
  project: ComicProject,
  language: string,
): ComicProject {
  return {
    ...project,
    language,
    languageIntent: { ...project.languageIntent, contentLanguage: language },
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
        elements.push(soundEffectElement(panel, soundEffect, index))
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
      const letteringType = (element: ComicTextElement) => element.letteringType
        ?? (element.bubble === 'caption' ? 'caption' : element.bubble === 'none' ? 'sound-effect' : 'dialogue')
      planned.captions = text.filter(element => letteringType(element) === 'caption').map(element => element.content)
      planned.soundEffects = text.filter(element => letteringType(element) === 'sound-effect').map(element => element.content)
      const existingDialogue = planned.dialogue
      planned.dialogue = text
        .filter(element => letteringType(element) === 'dialogue')
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

function provenanceId(value: unknown, path: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Invalid comic provenance: ${path} must be a non-empty ID`)
  }
  return value.trim()
}

function provenanceRevision(value: unknown, path: string): number {
  const revision = Number(value)
  if (!Number.isSafeInteger(revision) || revision < 0) {
    throw new Error(`Invalid comic provenance: ${path} must be a non-negative revision`)
  }
  return revision
}

function provenanceTimestamp(value: unknown, path: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Invalid comic provenance: ${path} must be a timestamp`)
  }
  return value.trim()
}

function provenanceIds(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid comic provenance: ${path} must be an ID list`)
  }
  return Array.from(new Set(value.map((item, index) => provenanceId(item, `${path}[${index}]`))))
}

/**
 * Normalize and validate the persisted Comic lineage contract.
 *
 * This deliberately throws for a present-but-invalid provenance object. An
 * invalid source must be visible to the caller; silently dropping it would
 * make a reload fall back to a title or the currently selected project.
 */
export function normalizeComicProvenance(value: unknown): ComicProvenance | undefined {
  if (value == null) return undefined
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid comic provenance: expected an object')
  }
  const raw = value as Record<string, unknown>
  if (raw.schema !== 'comic-provenance-v1') {
    throw new Error('Invalid comic provenance: unsupported schema')
  }
  const source = raw.source
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    throw new Error('Invalid comic provenance: source is required')
  }
  const sourceRaw = source as Record<string, unknown>
  if (sourceRaw.kind !== 'series_episode') {
    throw new Error('Invalid comic provenance: unsupported source kind')
  }
  const destination = raw.destination
  if (!destination || typeof destination !== 'object' || Array.isArray(destination)) {
    throw new Error('Invalid comic provenance: destination is required')
  }
  const destinationRaw = destination as Record<string, unknown>
  const optionalIds = (path: string) => destinationRaw[path] == null
    ? undefined : provenanceId(destinationRaw[path], `destination.${path}`)
  const optionalOutputIds = destinationRaw.outputAssetIds == null
    ? undefined : provenanceIds(destinationRaw.outputAssetIds, 'destination.outputAssetIds')
  const actor = raw.actor
  if (actor !== 'user' && actor !== 'wizard' && actor !== 'system') {
    throw new Error('Invalid comic provenance: actor is invalid')
  }
  return {
    schema: 'comic-provenance-v1',
    workspaceId: provenanceId(raw.workspaceId, 'workspaceId'),
    source: {
      kind: 'series_episode',
      seriesId: provenanceId(sourceRaw.seriesId, 'source.seriesId'),
      seriesRevision: provenanceRevision(sourceRaw.seriesRevision, 'source.seriesRevision'),
      episodeId: provenanceId(sourceRaw.episodeId, 'source.episodeId'),
      episodeUpdatedAt: provenanceTimestamp(sourceRaw.episodeUpdatedAt, 'source.episodeUpdatedAt'),
      productionIds: provenanceIds(sourceRaw.productionIds, 'source.productionIds'),
      outputAssetIds: provenanceIds(sourceRaw.outputAssetIds, 'source.outputAssetIds'),
    },
    destination: {
      comicId: provenanceId(destinationRaw.comicId, 'destination.comicId'),
      ...(optionalIds('productionId') ? { productionId: optionalIds('productionId') } : {}),
      ...(optionalIds('runId') ? { runId: optionalIds('runId') } : {}),
      ...(optionalIds('taskId') ? { taskId: optionalIds('taskId') } : {}),
      ...(optionalIds('rootTaskId') ? { rootTaskId: optionalIds('rootTaskId') } : {}),
      ...(optionalOutputIds ? { outputAssetIds: optionalOutputIds } : {}),
    },
    actor,
    tool: provenanceId(raw.tool, 'tool'),
    capability: provenanceId(raw.capability, 'capability'),
    createdAt: provenanceTimestamp(raw.createdAt, 'createdAt'),
  }
}

export function normalizeComicProject(raw: unknown): ComicProject {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid comic project')
  const doc = raw as Record<string, unknown>
  if (doc.version === 2 && Array.isArray(doc.pages)) {
    const project = repairComicText(doc as unknown as ComicProject)
    project.provenance = normalizeComicProvenance(project.provenance)
    if (project.provenance && project.provenance.destination.comicId !== project.id) {
      throw new Error('Invalid comic provenance: destination.comicId does not match project.id')
    }
    project.languageIntent = normalizeLanguageIntent(project.languageIntent, {
      contentLanguage: project.language || 'English',
      technicalPromptLanguage: 'en',
    })
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
    project.pages = project.pages.map(page => ({
      ...page,
      elements: page.elements.flatMap<ComicElement>(element => {
        if (element.type !== 'text') return [element]
        const letteringType = element.letteringType
          ?? (element.bubble === 'caption' ? 'caption' : element.bubble === 'none' ? 'sound-effect' : 'dialogue')
        if (letteringType === 'sound-effect' && isIncompleteSoundEffect(element.content)) return []
        if (letteringType !== 'sound-effect' || element.bubble !== 'none') {
          return [{ ...element, letteringType }]
        }
        // Upgrade legacy floating yellow SFX to the readable generated style.
        return [{
          ...element,
          letteringType,
          bubble: 'burst' as const,
          color: '#111111',
          bubbleBackground: '#fff4a3',
          bubbleStrokeColor: '#111111',
          bubbleStrokeWidth: 3,
          bubblePadding: Math.max(12, element.bubblePadding ?? 0),
          bubbleShadow: true,
        }]
      }),
    }))
    if (project.director) {
      project.director.scriptVersion = Number(project.director.scriptVersion || 1)
      project.director.plan = normalizeComicPlan(
        project.director.plan,
        project.director.input?.dialogueDensity || 'medium',
      )
      project.director.input.writingProvider = project.director.input.writingProvider || 'maestro'
      project.director.input.useGlobalProfile = project.director.input.useGlobalProfile === true
      if (project.director.input.writingProvider === 'openai-compatible') {
        const legacyUrl = project.director.input.writingBaseUrl || ''
        if (/api\.deepseek\.com/i.test(legacyUrl)) project.director.input.writingProvider = 'deepseek'
        else if (/api\.openai\.com/i.test(legacyUrl)) project.director.input.writingProvider = 'openai'
      }
      if (project.director.input.writingProvider === 'deepseek') {
        if (!project.director.input.writingModel || ['deepseek-chat', 'deepseek-reasoner'].includes(project.director.input.writingModel)) {
          project.director.input.writingModel = 'deepseek-v4-pro'
        }
        project.director.input.writingBaseUrl = 'https://api.deepseek.com'
      } else if (project.director.input.writingProvider === 'minimax') {
        if (!['MiniMax-M3', 'MiniMax-M2.7', 'MiniMax-M2.7-highspeed'].includes(project.director.input.writingModel || '')) {
          project.director.input.writingModel = 'MiniMax-M3'
        }
        project.director.input.writingBaseUrl = 'https://api.minimax.io/v1'
      }
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
