import type { DetailedHTMLProps, HTMLAttributes } from 'react'

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'model-viewer': DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        src?: string
        alt?: string
        'camera-controls'?: boolean
        'auto-rotate'?: boolean
        'shadow-intensity'?: string
        'camera-orbit'?: string
        orientation?: string
        'interaction-prompt'?: 'auto' | 'none'
        'rotation-per-second'?: string
        // glTF animation playback (rigged Maestro outputs)
        autoplay?: boolean
        'animation-name'?: string
        'animation-crossfade-duration'?: string
        exposure?: string
        loading?: 'auto' | 'lazy' | 'eager'
      }
    }
  }
}
