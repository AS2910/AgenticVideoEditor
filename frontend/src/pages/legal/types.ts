/** The policy drafts as data (G6, v2): each page is a title, a one-line summary and sections of
 *  blocks. Written for the lawyer to mark up, so every open point is a `counsel` note. */

/** An outside service Voltage sends data to, read from the adapters and config. */
export interface Vendor {
  name: string
  does: string
  gets: string
  why: string
  when: string
  where: string
}

/** A paragraph, a bulleted list, a note for the lawyer, a link to another page, or the vendor list. */
export type Block =
  | string
  | string[]
  | { counsel: string }
  | { before: string; link: string; href: string }
  | { vendors: Vendor[] }

/** `draft`: a section new or rewritten since the last review, shown with a "New, pending legal review"
 *  stamp so counsel can find it. Its value says what changed it (Voice consent V1 step 8: 'v3 2026-10-31').
 *  Remove it once the lawyer has reviewed the section. */
export interface Section { h: string; blocks: Block[]; draft?: string }

export interface LegalText {
  title: string
  summary: string
  sections: Section[]
}
