import { useId } from 'react'
import { useUiTranslation } from '../../i18n'

const COMMON_LANGUAGES = [
  'Español',
  'English',
  'Français',
  'Deutsch',
  'Italiano',
  'Português',
  'Català',
  '中文',
  '日本語',
  '한국어',
  'العربية',
  'हिन्दी',
  'Русский',
]

export function EditableLanguageInput({
  value,
  onChange,
  className = '',
  placeholder,
  label,
  required = false,
}: {
  value: string
  onChange: (value: string) => void
  className?: string
  placeholder?: string
  /** Visible field name. Falls back to the placeholder when the caller has no separate label. */
  label?: string
  required?: boolean
}) {
  const { t } = useUiTranslation('common')
  const listId = useId()
  const hint = placeholder ?? t('language.placeholder')
  return (
    <>
      <input
        aria-label={label ?? hint}
        list={listId}
        className={className}
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={hint}
        autoComplete="off"
        required={required}
        aria-required={required}
      />
      <datalist id={listId}>
        {COMMON_LANGUAGES.map(language => (
          <option key={language} value={language} />
        ))}
      </datalist>
    </>
  )
}
