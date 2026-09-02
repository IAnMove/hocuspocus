export type SidebarSlice = {
  sidebarOpen: boolean
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
}

type SetSidebarState = (
  partial: Partial<SidebarSlice> | ((state: SidebarSlice) => Partial<SidebarSlice>),
) => void

type GetSidebarState = () => SidebarSlice

export function createSidebarSlice(set: SetSidebarState, get: GetSidebarState): SidebarSlice {
  return {
    sidebarOpen: false,
    toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
    setSidebarOpen: open => set({ sidebarOpen: open }),
  }
}
