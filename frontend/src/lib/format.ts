// Formats québécois : « 5,2 % », « 25 000 $ » (espaces insécables).
const NBSP = ' '

export function pct(v: number, digits = 1): string {
  return (v * 100).toLocaleString('fr-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits }) + NBSP + '%'
}

export function signedPct(v: number, digits = 1): string {
  return (v > 0 ? '+' : v < 0 ? '−' : '') + pct(Math.abs(v), digits)
}

export function money(v: number): string {
  return Math.round(v).toLocaleString('fr-CA') + NBSP + '$'
}

export function points(v: number): string {
  const p = Math.round(v * 1000) / 10
  return (p > 0 ? '+' : p < 0 ? '−' : '') + Math.abs(p).toLocaleString('fr-CA') + NBSP + 'pts'
}
