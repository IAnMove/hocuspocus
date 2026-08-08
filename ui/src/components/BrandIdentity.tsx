interface BrandIdentityProps {
  appVersion?: string
}

export function BrandIdentity({ appVersion }: BrandIdentityProps) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <img
        src="/loreframe-logo.png"
        alt="Loreframe Lab"
        className="w-7 h-7 shrink-0 object-contain"
        draggable={false}
      />
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5 leading-none">
          <span className="font-semibold text-sm whitespace-nowrap">Loreframe</span>
          {appVersion && <span className="text-[10px] text-text-muted font-normal">v{appVersion}</span>}
        </div>
        <span className="mt-1 block text-[7px] font-semibold uppercase tracking-[0.18em] leading-none text-accent-blue whitespace-nowrap">
          Experimental Lab
        </span>
      </div>
    </div>
  )
}
