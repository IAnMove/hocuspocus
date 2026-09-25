import type { ApiOutput } from '../../api/outputs'
import { useObjectUrl } from '../../lib/useObjectUrl'
import { InputImageThumbnail } from '../common/InputImageThumbnail'
import { ImageCropButton } from '../common/ImageCropButton'
import { useStore } from '../../stores/useStore'
import { ImagePreview } from '../common/ImagePreview'

export function EditableImageReference({ file }: { file: File }) {
  const url = useObjectUrl(file)
  if (!url) return null
  const item: ApiOutput = { name: file.name, url, type: 'image', mode: null, size: file.size, created_at: 0 }
  return <>
    <ImagePreview image={{ ...item, type: 'image' }} className="h-full w-full"><InputImageThumbnail item={item} /></ImagePreview>
    <div className="absolute bottom-0 left-0">
      <ImageCropButton key={url} item={item} onReplace={(_saved, cropped) => {
        useStore.setState(state => ({ imageRefs: state.imageRefs.map(current => current === file ? cropped : current) }))
      }} />
    </div>
  </>
}
