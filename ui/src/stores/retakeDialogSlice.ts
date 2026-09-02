import type { SliceCreator } from './storeApi'

export type RetakeDialogSlice = {
  retakeDialogOpen: boolean
  retakeSourceFile: string | null
  openRetakeDialog: (filename: string) => void
  closeRetakeDialog: () => void
}

export const createRetakeDialogSlice: SliceCreator<RetakeDialogSlice> = set => ({
  retakeDialogOpen: false,
  retakeSourceFile: null,
  openRetakeDialog: filename => set({ retakeDialogOpen: true, retakeSourceFile: filename }),
  closeRetakeDialog: () => set({ retakeDialogOpen: false, retakeSourceFile: null }),
})
