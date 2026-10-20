import type { ExportPreset, ExportPresetPage } from '../types'

/** B3: a file's size as people read it. */
export const fileSize = (bytes: number) => (bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`)

/** F6: the token in a share link (`#s/<token>`), or null. */
export const shareToken = (hash: string): string | null => {
  const m = /^#\/?s\/([A-Za-z0-9_.-]+)$/.exec(hash.trim())
  return m ? m[1] : null
}

/** One preset as a line of facts: "Reels 9:16 · H.264 · -14 LUFS · No captions". */
export function presetFacts(p: ExportPreset, page: ExportPresetPage | null): string {
  const platform = page?.platforms.find((x) => x.id === p.platform)?.label ?? p.platform
  const codec = page?.codecs.find((x) => x.id === p.codec)?.label ?? p.codec
  return [platform, codec, `${p.loudness} LUFS`, p.captions ? 'Captions burned in' : 'No captions'].join(' · ')
}
