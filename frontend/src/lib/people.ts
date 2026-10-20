import type { Me } from '../api'

/** Who saved something, as a page says it: "you" for your own saves (A1). */
export function editorName(by: string | null | undefined, me: Me | null): string {
  if (!by) return 'someone'
  if (by === 'local' || (me?.user && (by === me.user.sub || by === me.user.email))) return 'you'
  return by
}
