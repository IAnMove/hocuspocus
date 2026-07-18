import { toPng } from 'html-to-image'
import { jsPDF } from 'jspdf'
import JSZip from 'jszip'
import { useComicStore } from './store'

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

