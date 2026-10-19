import { lazy, Suspense, useEffect, useState } from 'react'
import type { Scene } from '../../types'
import i18n, { useUiTranslation } from '../../i18n'
import { PENDING_SCENE_KEY } from '../../lib/sceneOutput'
import { serializeSceneFile } from '../../lib/sceneFile'
import { SceneTemplateGallery } from './SceneTemplateGallery'
import { SceneShowcaseGallery } from './SceneShowcaseGallery'
import { parseShowcaseManifest, type ShowcaseManifest } from './showcaseManifest'

const Editor = lazy(() => import('../../components/Sidebar/SceneAnimatorPanel').then(module => ({ default: module.SceneAnimatorPanel })))

/** A real application route, also usable by the provider-free local gallery
 * harness. The scene snapshot is handed to the existing editor, not rebuilt
 * from a movie or rendered by a special gallery-only implementation. */
export default function SceneTemplateReviewPage() {
  const { t } = useUiTranslation('scene3d')
  const editor = new URLSearchParams(window.location.search).get('editor') === '1'
  const [showcase, setShowcase] = useState<ShowcaseManifest | null>(null)
  const [variant, setVariant] = useState<'original' | 'showcase'>('showcase')
  const [showcaseError, setShowcaseError] = useState('')
  useEffect(() => {
    if (editor) return
    const controller = new AbortController()
    void (async () => {
      const response = await fetch('/scene-showcase/manifest.json', { signal: controller.signal, redirect: 'error', cache: 'no-store' })
      // Stock SPA hosts can return their index.html for an optional, absent
      // package. Malformed JSON packages still fail visibly below.
      if (response.status === 404 || (response.ok && response.headers.get('content-type')?.includes('text/html'))) {
        await response.body?.cancel()
        if (!controller.signal.aborted) setVariant('original')
        return
      }
      if (!response.ok || !response.body) throw new Error(i18n.t('scene3d:templateErrors.showcaseLoadFailed'))
      const reader = response.body.getReader()
      const chunks: Uint8Array[] = []
      let size = 0
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > 1_000_000) { await reader.cancel(); throw new Error(i18n.t('scene3d:templateErrors.manifestTooLarge')) }
        chunks.push(value)
      }
      const bytes = new Uint8Array(size)
      let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
      const manifest = parseShowcaseManifest(JSON.parse(new TextDecoder().decode(bytes)))
      if (!controller.signal.aborted) setShowcase(manifest)
    })().catch(error => {
      if (!controller.signal.aborted) { setShowcaseError((error as Error).message); setVariant('original') }
    })
    return () => controller.abort()
  }, [editor])
  const open = (scene: Scene) => {
    try {
      sessionStorage.setItem(PENDING_SCENE_KEY, serializeSceneFile(scene))
      window.location.assign('/scene-template-review?editor=1')
    } catch {
      window.alert(t('templateErrors.transferFailed'))
    }
  }
  return <main className="h-screen overflow-auto bg-bg-primary text-text-primary">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
      <a href="/scene-template-review" className="font-semibold text-cyan-200">{t('templateErrors.labTitle')}</a>
      <span className="text-xs text-text-muted">{t('templateErrors.labDisclaimer')}</span>
      <a href="/" className="text-sm underline">{t('templateErrors.backHome')}</a>
    </header>
    {editor
      ? <Suspense fallback={<p className="p-6">{t('templateErrors.openingEditor')}</p>}><section className="h-[calc(100vh-70px)]"><Editor /></section></Suspense>
      : <>
        {showcase && <nav aria-label={t('templateErrors.galleryVariant')} className="flex flex-wrap gap-3 px-5 py-4">
          <button type="button" aria-pressed={variant === 'showcase'} onClick={() => setVariant('showcase')} className="rounded border border-cyan-300/50 px-4 py-2">{t('templateErrors.minimaxVariant')}</button>
          <button type="button" aria-pressed={variant === 'original'} onClick={() => setVariant('original')} className="rounded border border-border px-4 py-2">{t('templateErrors.originalVariant')}</button>
        </nav>}
        {showcaseError && <p role="alert" className="px-5 py-3 text-amber-200">{t('templateErrors.originalsStillAvailable', { message: showcaseError })}</p>}
        {variant === 'showcase' && showcase ? <SceneShowcaseGallery manifest={showcase} onOpenScene={open} /> : <SceneTemplateGallery onOpenScene={open} />}
      </>}
  </main>
}
