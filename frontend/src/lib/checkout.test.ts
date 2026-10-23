import { describe, it, expect, vi, afterEach } from 'vitest'
import { returnedFromCheckout, startCheckout, stripeUrl } from './checkout'
import type { BillingCheckout } from '../types'

const STRIPE: BillingCheckout = { provider: 'stripe', checkout_id: 'cs_test_1', url: 'https://checkout.stripe.com/c/pay/cs_test_1', total: 12, currency: 'USD', test_mode: true, client: null }
const RAZOR: BillingCheckout = { provider: 'razorpay', checkout_id: 'order_1', url: '', total: 999, currency: 'INR', test_mode: true,
  client: { key_id: 'rzp_test_x', order_id: 'order_1', amount: 99900, currency: 'INR', description: 'Top-up: 10 credits' } }

describe('launch blocker 5: real checkout', () => {
  afterEach(() => { delete (window as unknown as { Razorpay?: unknown }).Razorpay })

  it('follows only Stripe\'s own https page', () => {
    expect(stripeUrl('https://checkout.stripe.com/c/pay/x')).toBe('https://checkout.stripe.com/c/pay/x')
    expect(stripeUrl('http://checkout.stripe.com/c/pay/x')).toBeNull()
    expect(stripeUrl('https://evil.example/c/pay/x')).toBeNull()
    expect(stripeUrl('javascript:alert(1)')).toBeNull()
  })

  it('leaves for Stripe\'s page, and refuses any other address', async () => {
    const go = vi.fn()
    await expect(startCheckout(STRIPE, go)).resolves.toEqual({ kind: 'left' })
    expect(go).toHaveBeenCalledWith(STRIPE.url)
    await expect(startCheckout({ ...STRIPE, url: 'https://evil.example/' }, go)).rejects.toThrow('Nothing was charged')
    expect(go).toHaveBeenCalledTimes(1)
  })

  it('opens Razorpay with the order and hands back its signed payment, or says it was closed', async () => {
    let options: Record<string, unknown> = {}
    ;(window as unknown as { Razorpay: unknown }).Razorpay = class { constructor(o: Record<string, unknown>) { options = o } open() {
      (options.handler as (r: unknown) => void)({ razorpay_order_id: 'order_1', razorpay_payment_id: 'pay_1', razorpay_signature: 'sig' }) } }
    await expect(startCheckout(RAZOR)).resolves.toEqual({ kind: 'paid', paid: { order_id: 'order_1', payment_id: 'pay_1', signature: 'sig' } })
    expect(options).toMatchObject({ key: 'rzp_test_x', order_id: 'order_1', amount: 99900, currency: 'INR', name: 'Voltage' })
    ;(window as unknown as { Razorpay: unknown }).Razorpay = class { constructor(o: Record<string, unknown>) { options = o } open() {
      ((options.modal as { ondismiss: () => void }).ondismiss)() } }
    await expect(startCheckout(RAZOR)).resolves.toEqual({ kind: 'closed' })
  })

  it('reads the return from Stripe', () => {
    expect(returnedFromCheckout('?checkout=done')).toBe('done')
    expect(returnedFromCheckout('?checkout=cancelled')).toBe('cancelled')
    expect(returnedFromCheckout('?checkout=other')).toBeNull()
    expect(returnedFromCheckout('')).toBeNull()
  })
})
