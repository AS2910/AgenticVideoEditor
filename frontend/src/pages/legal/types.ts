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

export interface Section { h: string; blocks: Block[] }

export interface LegalText {
  title: string
  summary: string
  sections: Section[]
}
