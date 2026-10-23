import type { Me } from '../api'

/** Who saved something, as a page says it: "you" for your own saves (A1), else their address
 *  (`name`, from the server). Never an owner id like `acct:9aad…` (rehearsal item 7). */
export function editorName(by: string | null | undefined, me: Me | null, name?: string | null): string {
  if (!by) return 'someone'
  const u = me?.user
  if (by === 'local' || (u && (by === u.sub || by.endsWith(`:${u.sub}`) || by === u.email || (!!name && name === u.email)))) return 'you'
  if (name) return name
  if (by.startsWith('email:')) return by.slice(6)
  return /^[a-z]+:/.test(by) ? 'a teammate' : by
}
