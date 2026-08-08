import { useId } from 'react'

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
  placeholder = 'Choose or type any language',
  required = false,
}: {
  value: string
  onChange: (value: string) => void
  className?: string
  placeholder?: string
  required?: boolean
}) {
  const listId = useId()
  return (
    <>
      <input
        list={listId}
        className={className}
        value={value}
        onChange={event => onChange(event.target.value)}
        placeholder={placeholder}
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
