import { toPng } from 'html-to-image'
import { jsPDF } from 'jspdf'
import JSZip from 'jszip'
import { useComicStore } from './store'
import type { ComicPanelElement } from './types'

const nextPaint = () => new Promise<void>(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

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
}

export async function forEachComicPanelCapture(
  consume: (capture: ComicPanelCapture, current: number, total: number) => Promise<void>,
  onProgress?: (current: number, total: number) => void,
  options: { includeLettering?: boolean } = {},
): Promise<void> {
  const state = useComicStore.getState()
  const originalPage = state.currentPageId
  const originalZoom = state.zoom
  const originalSelection = state.selectedId
  const total = state.project.pages.reduce((sum, page) => sum + page.elements.filter(element => element.type === 'panel' && !element.parentId).length, 0)
  let current = 0
  state.setSelected(null)
  state.setZoom(1)
  try {
    for (let pageIndex = 0; pageIndex < state.project.pages.length; pageIndex += 1) {
      const page = state.project.pages[pageIndex]
      useComicStore.getState().setCurrentPage(page.id)
      await nextPaint()
      const panels = page.elements
        .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
        .sort((a, b) => a.zIndex - b.zIndex)
      for (let panelIndex = 0; panelIndex < panels.length; panelIndex += 1) {
        const panel = panels[panelIndex]
        const node = document.querySelector<HTMLElement>(`[data-comic-element="${CSS.escape(panel.id)}"]`)
        if (!node) throw new Error(`Comic panel ${pageIndex + 1}.${panelIndex + 1} is not mounted`)
        const letteringIds = new Set(
          page.elements
            .filter(element => element.type === 'text' && element.parentId === panel.id)
            .map(element => element.id),
        )
        current += 1
        onProgress?.(current, total)
        const capture = {
          dataUrl: await toPng(node, {
            pixelRatio: 2,
            cacheBust: true,
            width: Math.round(panel.width),
            height: Math.round(panel.height),
            style: { left: '0', top: '0', transform: 'none', boxShadow: 'none' },
            ...(options.includeLettering === false ? {
              filter: child => !(
                child instanceof HTMLElement
                && letteringIds.has(child.dataset.comicElement || '')
              ),
            } : {}),
          }),
          pageNumber: pageIndex + 1,
          panelNumber: panelIndex + 1,
          panelId: panel.id,
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
