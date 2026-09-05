import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'

export interface StoryLabNavigationTab<T extends string = string> {
  id: T
  label: string
  icon: LucideIcon
}

interface StoryLabNavigationProps<T extends string> {
  tabs: Array<StoryLabNavigationTab<T>>
  activeTab: T
  onChange: (tab: T) => void
  notes: ReactNode
}

export function StoryLabNavigation<T extends string>({ tabs, activeTab, onChange, notes }: StoryLabNavigationProps<T>) {
  const { t } = useUiTranslation('storyLab')
  return (
    <nav aria-label="Story Lab sections" className="flex w-full shrink-0 gap-1 overflow-x-auto border-b border-border bg-bg-secondary p-2 md:w-48 md:flex-col md:overflow-x-hidden md:overflow-y-auto md:border-b-0 md:border-r">
      {tabs.map(item => (
        <button
          key={item.id}
          type="button"
          aria-current={activeTab === item.id ? 'page' : undefined}
          onClick={() => onChange(item.id)}
          className={`flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-2 text-xs md:w-full ${activeTab === item.id ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'}`}
        >
          <item.icon size={14} aria-hidden="true" /> <span>{item.label}</span>
        </button>
      ))}
      <span className="shrink-0 self-center px-1 text-[9px] text-text-muted md:hidden" aria-hidden="true">{t('nav.swipe')}</span>
      <div className="hidden space-y-1.5 border-t border-border pt-3 text-[9px] text-text-muted md:block">
        {notes}
      </div>
    </nav>
  )
}
