import { usd } from '../pages/fmt'

/** A2: what a finished project check cost, in words: free for the rule checks, never a made-up figure. */
export function costWord(mode: 'full' | 'rules', cost: number): string {
  if (mode === 'rules' || cost <= 0) return 'rule checks only, free'
  return cost < 0.01 ? 'with the text pass, under $0.01' : `with the text pass, ${usd(cost)}`
}
