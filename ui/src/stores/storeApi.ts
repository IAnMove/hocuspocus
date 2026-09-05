/** Typed Zustand slice binding so composers do not use `as never`. */

export type SliceSet<T> = (
  partial: Partial<T> | ((state: T) => Partial<T>),
) => void

export type SliceGet<T> = () => T

export type SliceCreator<TSlice, THost extends TSlice = TSlice> = (
  set: SliceSet<THost>,
  get: SliceGet<THost>,
) => TSlice

/**
 * Bind a slice to the full store. `TStore` must include the slice keys, so a
 * `Partial<TSlice>` is a valid store update without `as never`.
 *
 * `THost` defaults to the slice itself. A slice may declare a wider host when
 * it reads or writes sibling fields without owning those domains.
 */
export function bindSlice<TSlice extends object, TStore extends TSlice>(
  set: SliceSet<TStore>,
  get: SliceGet<TStore>,
  create: SliceCreator<TSlice, TStore>,
): TSlice {
  return create(set, get)
}
