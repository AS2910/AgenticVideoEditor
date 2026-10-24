import type { ReactNode } from 'react'
import { AuditSection } from './AuditSection'
import { AdminWaitlist } from '../AdminWaitlist'
import { BetaFeedbackSection } from './BetaFeedbackSection'
import { BetaSection } from './BetaSection'
import { ConsentReviewsSection } from './ConsentReviewsSection'
import { card } from './ui'

/** The admin page's mount point (rehearsal item 10). Each later admin tool is one
 *  entry here: an id (also its in-page anchor), the jump-list label, and what to
 *  draw (it gets the shared card class). Sections show in this order, after
 *  Spend today, People and Features for one person, and before the numbers.
 *  For example:  { id: 'waitlist', label: 'Waitlist', render: (c) => <WaitlistSection card={c} /> },
 *  A page of its own (like #admin/emails) adds a link instead: { id: 'emails', label: 'Emails', href: '#admin/emails' }. */
export interface AdminSection { id: string; label: string; render?: (card: string) => ReactNode; href?: string }

export const ADMIN_SECTIONS: AdminSection[] = [
  // ── other admin sections go here, one line each ──
  { id: 'waitlist', label: 'Waitlist', render: (c) => <AdminWaitlist card={c} /> },
  { id: 'emails', label: 'Emails', href: '#admin/emails' },
  { id: 'beta-cohort', label: 'Beta', render: (c) => <BetaSection card={c} /> },
  { id: 'beta', label: 'Beta feedback', render: (c) => <BetaFeedbackSection card={c} /> },
  { id: 'consent', label: 'Consent reviews', render: (c) => <ConsentReviewsSection card={c} /> },
  { id: 'audit', label: 'Audit trail', render: (c) => <AuditSection card={c} /> },
]

export { card }
