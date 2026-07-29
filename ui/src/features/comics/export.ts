import { toPng } from 'html-to-image'
import { jsPDF } from 'jspdf'
import JSZip from 'jszip'
import { useComicStore } from './store'
import type { ComicPanelElement } from './types'

const nextPaint = () => new Promise<void>(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

async function waitForComicMedia(node: HTMLElement) {
  if (document.fonts?.ready) await document.fonts.ready
  await Promise.all(
    Array.from(node.querySelectorAll('img')).map(async image => {
      if (!image.complete) {
        await new Promise<void>(resolve => {
          image.addEventListener('load', () => resolve(), { once: true })
          image.addEventListener('error', () => resolve(), { once: true })
        })
      }
      if (typeof image.decode === 'function') {
        await image.decode().catch(() => undefined)
      }
    }),
  )
  await nextPaint()
}

async function loadCapturedImage(dataUrl: string) {
  const image = new Image()
  image.decoding = 'sync'
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('Could not decode the captured comic page'))
    image.src = dataUrl
  })
  return image
}

function cropPanelFromPage(
  pageImage: HTMLImageElement,
  pageWidth: number,
  pageHeight: number,
  panel: ComicPanelElement,
) {
  const scaleX = pageImage.naturalWidth / pageWidth
  const scaleY = pageImage.naturalHeight / pageHeight
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(panel.width * scaleX))
  canvas.height = Math.max(1, Math.round(panel.height * scaleY))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable while capturing the comic')
  context.drawImage(
    pageImage,
    Math.round(panel.x * scaleX),
    Math.round(panel.y * scaleY),
    canvas.width,
    canvas.height,
    0,
    0,
    canvas.width,
    canvas.height,
  )
  return canvas.toDataURL('image/png')
}

const safeName = (name: string) =>
  name.trim().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '').toLowerCase() || 'comic'

export async function captureComicPage(pixelRatio = 1): Promise<string> {
  const state = useComicStore.getState()
  const selected = state.selectedId
  const zoom = state.zoom
  state.setSelected(null)
  state.setZoom(1)
  await nextPaint()
  try {
    const node = document.getElementById('maestro-comic-page')
    if (!node) throw new Error('Comic page is not mounted')
    return await toPng(node, {
      pixelRatio,
      cacheBust: true,
      style: { transform: 'none', boxShadow: 'none' },
    })
  } finally {
    state.setZoom(zoom)
    state.setSelected(selected)
  }
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function exportComicPagePng() {
  const state = useComicStore.getState()
  const pageIndex = state.project.pages.findIndex(page => page.id === state.currentPageId)
  const dataUrl = await captureComicPage(2)
  const response = await fetch(dataUrl)
  downloadBlob(await response.blob(), `${safeName(state.project.title)}-page-${pageIndex + 1}.png`)
}

async function captureAllPages(onProgress?: (current: number, total: number) => void) {
  const state = useComicStore.getState()
  const original = state.currentPageId
  const images: Array<{ dataUrl: string; width: number; height: number }> = []
  try {
    for (let index = 0; index < state.project.pages.length; index++) {
      const page = state.project.pages[index]
      useComicStore.getState().setCurrentPage(page.id)
      await nextPaint()
      onProgress?.(index + 1, state.project.pages.length)
      images.push({ dataUrl: await captureComicPage(2), width: page.width, height: page.height })
    }
  } finally {
    useComicStore.getState().setCurrentPage(original)
  }
  return images
}

export type ComicPanelCapture = {
  dataUrl: string
  pageNumber: number
  panelNumber: number
  panelId: string
  width: number
  height: number
}

export async function forEachComicPanelCapture(
  consume: (capture: ComicPanelCapture, current: number, total: number) => Promise<void>,
  onProgress?: (current: number, total: number) => void,
  options: { includeLettering?: boolean; limit?: number } = {},
): Promise<void> {
  const state = useComicStore.getState()
  const originalPage = state.currentPageId
  const originalZoom = state.zoom
  const originalSelection = state.selectedId
  const available = state.project.pages.reduce((sum, page) => sum + page.elements.filter(element => element.type === 'panel' && !element.parentId).length, 0)
  const requestedLimit = Number.isFinite(Number(options.limit))
    ? Math.max(1, Math.floor(Number(options.limit)))
    : available
  const total = Math.min(available, requestedLimit)
  let current = 0
  state.setSelected(null)
  state.setZoom(1)
  try {
    for (let pageIndex = 0; pageIndex < state.project.pages.length; pageIndex += 1) {
      if (current >= total) break
      const page = state.project.pages[pageIndex]
      useComicStore.getState().setCurrentPage(page.id)
      await nextPaint()
      const panels = page.elements
        .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
        .sort((a, b) => a.zIndex - b.zIndex)
      const pageNode = document.getElementById('maestro-comic-page')
      if (!pageNode) throw new Error(`Comic page ${pageIndex + 1} is not mounted`)
      await waitForComicMedia(pageNode)
      const letteringIds = new Set(
        page.elements
          .filter(element => element.type === 'text')
          .map(element => element.id),
      )
      // Capture the rendered page once, then crop every panel from that stable
      // bitmap. Repeated html-to-image calls on detached panel subtrees could
      // return black after the first panel on each page.
      const pageCapture = await toPng(pageNode, {
        pixelRatio: 2,
        cacheBust: true,
        style: { transform: 'none', boxShadow: 'none' },
        ...(options.includeLettering === false ? {
          filter: child => !(
            child instanceof HTMLElement
            && letteringIds.has(child.dataset.comicElement || '')
          ),
        } : {}),
      })
      const pageImage = await loadCapturedImage(pageCapture)
      for (let panelIndex = 0; panelIndex < panels.length; panelIndex += 1) {
        if (current >= total) break
        const panel = panels[panelIndex]
        current += 1
        onProgress?.(current, total)
        const capture = {
          dataUrl: cropPanelFromPage(pageImage, page.width, page.height, panel),
          pageNumber: pageIndex + 1,
          panelNumber: panelIndex + 1,
          panelId: panel.id,
          width: panel.width,
          height: panel.height,
        }
        // Wait for the consumer (normally upload) before capturing the next
        // panel. Once this callback resolves the large data URL can be
        // garbage-collected instead of accumulating for the whole comic.
        await consume(capture, current, total)
      }
    }
  } finally {
    useComicStore.getState().setCurrentPage(originalPage)
    useComicStore.getState().setZoom(originalZoom)
    useComicStore.getState().setSelected(originalSelection)
  }
}

export async function exportComicPdf(onProgress?: (current: number, total: number) => void) {
  const project = useComicStore.getState().project
  const pages = await captureAllPages(onProgress)
  if (!pages.length) return
  const first = pages[0]
  const pdf = new jsPDF({
    orientation: first.width > first.height ? 'landscape' : 'portrait',
    unit: 'px',
    format: [first.width, first.height],
    hotfixes: ['px_scaling'],
  })
  pages.forEach((page, index) => {
    if (index > 0) {
      pdf.addPage([page.width, page.height], page.width > page.height ? 'landscape' : 'portrait')
    }
    pdf.addImage(page.dataUrl, 'PNG', 0, 0, page.width, page.height, undefined, 'FAST')
  })
  pdf.save(`${safeName(project.title)}.pdf`)
}

export async function exportComicCbz(onProgress?: (current: number, total: number) => void) {
  const project = useComicStore.getState().project
  const pages = await captureAllPages(onProgress)
  const zip = new JSZip()
  pages.forEach((page, index) => {
    zip.file(`page-${String(index + 1).padStart(3, '0')}.png`, page.dataUrl.split(',')[1], { base64: true })
  })
  downloadBlob(await zip.generateAsync({ type: 'blob' }), `${safeName(project.title)}.cbz`)
}

export function exportComicJson() {
  const project = useComicStore.getState().project
  downloadBlob(
    new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' }),
    `${safeName(project.title)}.comic.json`,
  )
}
