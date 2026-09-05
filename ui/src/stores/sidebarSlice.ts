import type { SliceCreator } from './storeApi'

export type SidebarSlice = {
  sidebarOpen: boolean
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
}

export const createSidebarSlice: SliceCreator<SidebarSlice> = (set, get) => ({
  sidebarOpen: false,
  toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
  setSidebarOpen: open => set({ sidebarOpen: open }),
})
