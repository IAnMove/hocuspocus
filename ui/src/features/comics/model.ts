import type {
  ComicElement,
  ComicPage,
  ComicPanelElement,
  ComicPlan,
  ComicProject,
  ComicTextElement,
} from './types'

export const comicId = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${crypto.randomUUID().slice(0, 8)}`

export const COMIC_FORMATS = {
  a4: { width: 800, height: 1131, dpi: 300, label: 'A4 portrait' },
  'us-comic': { width: 800, height: 1231, dpi: 300, label: 'US Comic' },
  square: { width: 1080, height: 1080, dpi: 144, label: 'Square' },
  webtoon: { width: 800, height: 2400, dpi: 144, label: 'Webtoon' },
} as const

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
      promptSuffix: 'professional sequential comic art, expressive ink, clean composition',
      fontFamily: '"Comic Sans MS", "Trebuchet MS", sans-serif',
      palette: ['#ffffff', '#111111', '#facc15', '#ef4444'],
    },
    pageNumbering: { style: 'plain' },
    characters: [],
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

export function textElement(
  panel: ComicPanelElement,
  content: string,
  bubble: ComicTextElement['bubble'],
  order: number,
): ComicTextElement {
  const width = Math.max(120, panel.width * 0.76)
  const height = Math.max(72, Math.min(160, 54 + content.length * 0.42))
  return {
    id: comicId('text'),
    type: 'text',
    parentId: panel.id,
    x: panel.width * 0.12,
    y: bubble === 'caption' ? 10 + order * 76 : panel.height - height - 18 - order * 18,
    width,
    height,
    rotation: 0,
    zIndex: 20 + order,
    visible: true,
    content,
    fontSize: bubble === 'caption' ? 18 : 20,
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
  const project = base ?? createComicProject()
  const pages = plan.pages.map(planPage => {
    const page = createComicPage(project.format.width, project.format.height)
    const panels = panelsForCount(page, Math.max(1, planPage.panels.length))
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

export function normalizeComicProject(raw: unknown): ComicProject {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid comic project')
  const doc = raw as Record<string, unknown>
  if (doc.version === 2 && Array.isArray(doc.pages)) return doc as unknown as ComicProject
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
