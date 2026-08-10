export function timeFromX(
  clientX: number,
  rectLeft: number,
  rectWidth: number,
  duration: number,
): number {
  if (rectWidth <= 0) return 0
  const ratio = (clientX - rectLeft) / rectWidth
  const clamped = Math.min(1, Math.max(0, ratio))
  return clamped * duration
}
