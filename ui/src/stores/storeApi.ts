/** Typed Zustand slice binding so composers do not use `as never`. */

export type SliceSet<T> = (
  partial: Partial<T> | ((state: T) => Partial<T>),
) => void

export type SliceGet<T> = () => T

export type SliceCreator<T> = (set: SliceSet<T>, get: SliceGet<T>) => T

/**
 * Bind a slice to the full store. `TStore` must include the slice keys, so a
 * `Partial<TSlice>` is a valid store update without `as never`.
 */
export function bindSlice<TSlice extends object, TStore extends TSlice>(
  set: SliceSet<TStore>,
  get: SliceGet<TStore>,
  create: SliceCreator<TSlice>,
): TSlice {
  const sliceSet: SliceSet<TSlice> = partial => {
    if (typeof partial === 'function') {
      set(state => partial(state) as Partial<TStore>)
      return
    }
    set(partial as Partial<TStore>)
  }
  return create(sliceSet, get)
}
