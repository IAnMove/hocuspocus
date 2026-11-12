/** Widths and breakpoints for the shared desk. The desk does not know what it edits. */
export const OUTLINE_WIDTH_PX = 256
export const INSPECTOR_WIDTH_PX = 320
export const DRAWER_MAX_PX = 1100
export const PHONE_MAX_PX = 700

export type WorkbenchLayout = 'dock' | 'drawer' | 'stack'

/** `width` is the viewport width in pixels. 1100 and below uses a drawer; a phone stacks. */
export function workbenchLayout(width: number): WorkbenchLayout {
  if (width <= PHONE_MAX_PX) return 'stack'
  if (width <= DRAWER_MAX_PX) return 'drawer'
  return 'dock'
}
