/** Rehearsal item 1 (launch blocker 5): a real provider's checkout. With real keys the billing API
 *  answers a buy with `checkout` instead of an invoice: Stripe gives its hosted page (we go there and
 *  come back to `?checkout=done#billing`), Razorpay gives what checkout.js needs (we open it here and
 *  send its signed payment to /billing/razorpay/verify). Fake providers never answer with a checkout. */
import type { BillingCheckout } from '../types'

const RAZORPAY_JS = 'https://checkout.razorpay.com/v1/checkout.js'
const STRIPE_HOSTS = ['checkout.stripe.com']

export interface RazorpayPaid { order_id: string; payment_id: string; signature: string }

type RazorpayCtor = new (options: Record<string, unknown>) => { open: () => void }

/** Only Stripe's own https page is followed; anything else is refused (never an open redirect). */
export function stripeUrl(url: string): string | null {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' && STRIPE_HOSTS.includes(u.hostname) ? u.toString() : null
  } catch {
    return null
  }
}

function loadRazorpay(): Promise<RazorpayCtor> {
  const w = window as unknown as { Razorpay?: RazorpayCtor }
  if (w.Razorpay) return Promise.resolve(w.Razorpay)
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = RAZORPAY_JS
    s.async = true
    s.onload = () => (w.Razorpay ? resolve(w.Razorpay) : reject(new Error('Razorpay did not load.')))
    s.onerror = () => reject(new Error('Razorpay could not be reached. Nothing was charged. Try again.'))
    document.head.appendChild(s)
  })
}

/** What happened: `left` (we are going to Stripe's page), `paid` (Razorpay's signed payment, to verify),
 *  `closed` (the buyer closed Razorpay's window: nothing charged). */
export type CheckoutOutcome = { kind: 'left' } | { kind: 'paid'; paid: RazorpayPaid } | { kind: 'closed' }

export async function startCheckout(checkout: BillingCheckout, go: (url: string) => void = (u) => window.location.assign(u)): Promise<CheckoutOutcome> {
  if (checkout.url) {
    const url = stripeUrl(checkout.url)
    if (!url) throw new Error('The payment page address was not one we expected. Nothing was charged.')
    go(url)
    return { kind: 'left' }
  }
  const client = checkout.client
  if (!client) throw new Error('The payment could not be started. Nothing was charged.')
  const Razorpay = await loadRazorpay()
  return new Promise((resolve) => {
    const rzp = new Razorpay({
      key: client.key_id, order_id: client.order_id, amount: client.amount, currency: client.currency,
      name: 'Voltage', description: client.description,
      handler: (r: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) =>
        resolve({ kind: 'paid', paid: { order_id: r.razorpay_order_id, payment_id: r.razorpay_payment_id, signature: r.razorpay_signature } }),
      modal: { ondismiss: () => resolve({ kind: 'closed' }) },
    })
    rzp.open()
  })
}

/** `?checkout=done` or `?checkout=cancelled`, set by Stripe's return addresses. */
export function returnedFromCheckout(search: string = window.location.search): 'done' | 'cancelled' | null {
  const v = new URLSearchParams(search).get('checkout')
  return v === 'done' || v === 'cancelled' ? v : null
}

/** Drop `?checkout=` from the address once read, keeping the hash route. */
export function clearCheckoutParam(): void {
  const u = new URL(window.location.href)
  if (!u.searchParams.has('checkout')) return
  u.searchParams.delete('checkout')
  window.history.replaceState(null, '', u.pathname + (u.search ? u.search : '') + u.hash)
}
