import { useEffect, useState } from 'react'
import type { ApiOutput } from '../../api/outputs'
import { inputThumbnailSource } from '../../lib/inputImageThumbnail'
import { loadFitImage } from '../../lib/imageFit'

export function InputImageThumbnail({ item }: { item: ApiOutput }) {
  const source = inputThumbnailSource(item)
  const local = /^(blob:|data:)/.test(source)
  const [preview, setPreview] = useState<{ source: string; url: string } | null>(null)
  useEffect(() => {
    if (!local) return
    let cancelled = false, url = ''
    void loadFitImage(source).then(image => {
      if (cancelled) return
      const scale = Math.min(1, 160 / Math.max(image.naturalWidth, image.naturalHeight))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
      canvas.getContext('2d')?.drawImage(image, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(blob => {
        if (cancelled || !blob) return
        url = URL.createObjectURL(blob)
        setPreview({ source, url })
      }, 'image/png')
    }).catch(() => { /* Keep the placeholder; the editor reports decode errors. */ })
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [source, local])
  const url = local ? (preview?.source === source ? preview.url : '') : source
  return url ? <img src={url} alt={item.name} loading="lazy" decoding="async" className="h-full w-full object-contain" /> : <span aria-label={item.name} className="block h-full w-full bg-bg-active" />
}
