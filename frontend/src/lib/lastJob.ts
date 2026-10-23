/** Rehearsal item 11: the newest job the app has heard of (from the jobs model), so
 *  "Send feedback" can say which job someone was looking at. Kept in memory only. */
let last: { id: string; at: string } | null = null

export function noteJob(id: string, createdAt: string): void {
  if (!last || createdAt >= last.at) last = { id, at: createdAt }
}

export const lastJobId = (): string | null => last?.id ?? null

/** Tests only. */
export function resetLastJob(): void { last = null }
