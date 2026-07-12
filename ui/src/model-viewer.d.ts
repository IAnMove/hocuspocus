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
        'interaction-prompt'?: 'auto' | 'none'
        exposure?: string
        loading?: 'auto' | 'lazy' | 'eager'
      }
    }
  }
}
