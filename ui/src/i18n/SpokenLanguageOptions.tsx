import { useUiTranslation } from './index'

const OPTIONS = [
  { value: '', key: 'auto' },
  { value: 'Español de España', key: 'spain' },
  { value: 'Español latinoamericano', key: 'latam' },
  { value: 'English', key: 'english' },
  { value: 'French', key: 'french' },
  { value: 'Italian', key: 'italian' },
] as const

export function SpokenLanguageOptions() {
  const { t } = useUiTranslation('director')
  return (
    <>
      {OPTIONS.map(option => (
        <option key={option.value || 'auto'} value={option.value}>
          {t(`spoken.${option.key}`)}
        </option>
      ))}
    </>
  )
}
