export const DIAGNOSTICS_SCHEMA = 'hocuspocus.user-diagnostics-report' as const

export type RepairPath = {
  id: string
  summary: string
}

export type AvailabilityVersion = {
  app?: string | null
  recipe?: string | null
  python?: string | null
  torch?: string | null
  cuda?: string | null
}

export type AvailabilityItem = {
  kind: 'operation' | 'model'
  id: string
  available: boolean
  component: string
  driver: string | null
  backend: string
  ram_gb_observed: number | null
  vram_gb_observed: number | null
  version: AvailabilityVersion
  repair_path: RepairPath | null
  reasons: string[]
  weights?: string
}

export type EngineCapability = {
  id: string
  label?: string | null
  required: boolean
  supported: boolean
  installed: boolean
  reason?: string | null
  warning?: string | null
  recipe_id?: string | null
  python?: string | null
  torch?: string | null
  cuda?: string | null
  driver_minimum?: string | null
  repair_path: RepairPath | null
}

export type CorrelatedError = {
  task_id?: string
  intent_id?: string
  operation?: string
  status?: string
  job_id?: string
  workspace?: string
  code?: string
  message?: string
  oom?: {
    is_oom?: boolean
    current_coefficient?: number
    suggested_coefficient?: number | null
  }
}

export type ReportPack = {
  schema: typeof DIAGNOSTICS_SCHEMA
  schema_version: number
  generated_at?: string
  build: {
    app_version?: string | null
    git_revision?: string | null
    ui_build_id?: string | null
  }
  platform: {
    os: string
    architecture: string
    python?: string
    gpu?: string
    gpu_name?: string | null
    driver?: string | null
    backend: string
  }
  observed: {
    ram_gb: number | null
    vram_gb: number | null
    cpu_count?: number | null
  }
  capabilities: {
    engines: EngineCapability[]
  }
  availability: AvailabilityItem[]
  error: CorrelatedError | null
}

export type ReportCorrelation = {
  task_id?: string
  intent_id?: string
  workspace?: string
}
