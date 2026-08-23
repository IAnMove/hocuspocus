import type { DirectorClipImage } from '../../types'
import { useDirectorClipImageUrl } from '../../lib/directorClipImageUrl'

export function DirectorClipImagePreview({
  image,
  alt,
  className,
}: {
  image: DirectorClipImage
  alt: string
  className: string
}) {
  const src = useDirectorClipImageUrl(image)
  if (!src) return null
  return <img src={src} alt={alt} className={className} />
}
