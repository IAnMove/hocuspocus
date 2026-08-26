interface BrandIdentityProps {
  appVersion?: string
}

export function BrandIdentity({ appVersion }: BrandIdentityProps) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <img
        src="/hocuspocus-icon.png"
        alt="HocusPocus"
        className="w-7 h-7 shrink-0 object-contain"
        draggable={false}
      />
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5 leading-none">
          {/* Same face as the boot plate — the product signs its name
              the same way here as it does on the way in. Cormorant runs
              small for its point size, so 17px here optically matches
              the 14px sans it replaced; the row height is set by the
              28px mark either way. */}
          <span className="hp-wordmark font-semibold text-[17px] whitespace-nowrap">HocusPocus</span>
          {appVersion && <span className="text-[10px] text-text-muted font-normal">v{appVersion}</span>}
        </div>
        <span className="mt-1 block text-[7px] font-semibold uppercase tracking-[0.18em] leading-none text-accent-blue whitespace-nowrap">
          Creation Lab
        </span>
      </div>
    </div>
  )
}
