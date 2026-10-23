import { useEffect, useState } from 'react'
import type { MemberRole } from '../types'
import { getWorkspace } from '../api'

/** G2: your role in the workspace you are working in (asked once per page load, only with
 *  golive.g2 on; with it off everyone is their own owner). Null until known. Rehearsal
 *  2026-10-23: Billing is the owner's, so Editors and Reviewers are not offered it. */
let roleAsked: Promise<MemberRole | null> | null = null
export function useWorkspaceRole(on: boolean): MemberRole | null {
  const [role, setRole] = useState<MemberRole | null>(on ? null : 'owner')
  useEffect(() => {
    if (!on) { setRole('owner'); return }
    let live = true
    roleAsked ??= getWorkspace().then((v) => v.you.role).catch(() => { roleAsked = null; return null })
    void roleAsked.then((r) => { if (live) setRole(r) })
    return () => { live = false }
  }, [on])
  return role
}

/** Rehearsal item 7: a Reviewer only watches, so the pages leave out what they cannot do
 *  and say so once, in these words (the server refuses each change anyway). */
export const REVIEWER_NOTE = 'You are a Reviewer in this workspace, so you can watch what is shared with you. Ask the owner to make you an Editor to change things.'
