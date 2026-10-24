import { getMe } from '../api'
import type { Me } from '../api'

/** Run 4 item 4c: who is here, asked once when the app starts, so the calls made
 *  as the signed-in person (flags, onboarding, the media token) wait for the answer
 *  and are not made at all for someone signed out (the landing and sign-in pages
 *  logged a 401 for each). Without the app (a component on its own in a test) there
 *  is no answer to wait for and those calls go ahead as before. */

let asked: Promise<Me> | null = null

/** The app's start: ask the server who is here (once per mount of the app). */
export function askWhoIsHere(): Promise<Me> {
  asked = getMe()
  return asked
}

/** The answer the app asked for, or null when it has not asked. */
export function whoIsHere(): Promise<Me> | null {
  return asked
}

/** Whether there is someone to ask as: signed in, or sign-in is off. True with no
 *  answer to wait for, or when the answer failed (an older server opens as before). */
export async function signedInHere(): Promise<boolean> {
  if (!asked) return true
  try {
    const me = await asked
    return me.mode === 'off' || me.user !== null
  } catch {
    return true
  }
}

/** Tests: forget the answer. */
export function resetSession(): void {
  asked = null
}
