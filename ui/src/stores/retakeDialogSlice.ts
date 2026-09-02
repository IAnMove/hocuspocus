export type RetakeDialogSlice = {
  retakeDialogOpen: boolean
  retakeSourceFile: string | null
  openRetakeDialog: (filename: string) => void
  closeRetakeDialog: () => void
}

type SetRetakeDialogState = (
  partial: Partial<RetakeDialogSlice> | ((state: RetakeDialogSlice) => Partial<RetakeDialogSlice>),
) => void

export function createRetakeDialogSlice(set: SetRetakeDialogState): RetakeDialogSlice {
  return {
    retakeDialogOpen: false,
    retakeSourceFile: null,
    openRetakeDialog: filename => set({ retakeDialogOpen: true, retakeSourceFile: filename }),
    closeRetakeDialog: () => set({ retakeDialogOpen: false, retakeSourceFile: null }),
  }
}
