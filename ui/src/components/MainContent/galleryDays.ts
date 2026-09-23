import type { OutputFile } from '../../types'
import type { GallerySection } from './mediaGalleryLayout'

type Dated = Pick<OutputFile, 'created_at' | 'completed_at'>

function outputDate(file: Dated): Date {
  return new Date((file.completed_at ?? file.created_at) * 1000)
}

function sameDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate()
}

/** "Today", "Yesterday", or a weekday and date (with the year when it is not
 *  the current one), in the interface language. */
export function galleryDayLabel(date: Date, now: Date, locale: string, words: { today: string; yesterday: string }): string {
  if (sameDay(date, now)) return words.today
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  if (sameDay(date, yesterday)) return words.yesterday
  const label = new Intl.DateTimeFormat(locale, {
    weekday: 'long', day: 'numeric', month: 'long',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  }).format(date)
  return label.charAt(0).toLocaleUpperCase(locale) + label.slice(1)
}

/** One section per calendar day (local time) in list order. The list keeps
 *  the server's order, so newest-first and oldest-first both group cleanly. */
export function daySections(
  outputs: Dated[],
  locale: string,
  words: { today: string; yesterday: string },
  now: Date = new Date(),
): GallerySection[] {
  const sections: GallerySection[] = []
  let previous: Date | null = null
  outputs.forEach((file, index) => {
    const date = outputDate(file)
    if (previous && sameDay(previous, date)) return
    sections.push({ start: index, label: galleryDayLabel(date, now, locale, words) })
    previous = date
  })
  return sections
}
