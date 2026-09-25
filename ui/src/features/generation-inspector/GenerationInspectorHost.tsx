import { useEffect, useState } from 'react'
import { GenerationInspectorDialog } from './GenerationInspectorDialog'
import {
  attemptFromOpenRequest, listenForGenerationInspector, loadInspectedAttempt,
  persistInspectedAttempt,
} from './persistence'
import type { CatalogItem, CurrentModel, InspectedAttempt } from './types'
import { submitInspectorPlan } from './submit'

export function GenerationInspectorHost({
  workspace,
  catalog,
  currentModel,
  candidates,
}: {
  workspace: string
  catalog?: CatalogItem[]
  currentModel?: CurrentModel
  candidates?: InspectedAttempt[]
}) {
  const stored = loadInspectedAttempt(workspace)
  const [attempt, setAttempt] = useState<InspectedAttempt | null>(stored?.attempt || null)
  const [open, setOpen] = useState(Boolean(stored?.open && stored.attempt))
  const [folder, setFolder] = useState(workspace)
  if (folder !== workspace) {
    setFolder(workspace)
    const next = loadInspectedAttempt(workspace)
    setAttempt(next?.attempt || null)
    setOpen(Boolean(next?.open && next.attempt))
  }

  useEffect(() => listenForGenerationInspector(request => {
    const inspected = attemptFromOpenRequest(request)
    if (!inspected) return
    persistInspectedAttempt(request.workspace, inspected, true)
    if (request.workspace !== workspace) return
    setAttempt(inspected)
    setOpen(true)
  }), [workspace])

  if (!attempt) return null
  return (
    <GenerationInspectorDialog
      key={`${workspace}:${attempt.attemptId}`}
      open={open}
      onClose={() => {
        setOpen(false)
        persistInspectedAttempt(workspace, attempt, false)
      }}
      attempt={attempt}
      workspace={workspace}
      catalog={catalog}
      currentModel={currentModel}
      candidates={candidates}
      onGenerate={submitInspectorPlan}
    />
  )
}
