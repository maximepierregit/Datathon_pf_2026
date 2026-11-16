// Formats québécois : « 5,2 % », « 25 000 $ » (espaces insécables).
import type { Contribution, ContributionFrequency, Evidence, Holding } from '../types'

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

/** « +1 446 $ », « −5 074 $ » : un montant avec son signe. */
export function signedMoney(v: number): string {
  return (v > 0 ? '+' : v < 0 ? '−' : '') + money(Math.abs(v))
}

/** Des points de pourcentage déjà en pourcentage (−1,5 → « −1,5 % »), pour les étiquettes des axes. */
export function percentPoints(v: number, digits = 1): string {
  return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toLocaleString('fr-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits }) + NBSP + '%'
}

export function points(v: number): string {
  const p = Math.round(v * 1000) / 10
  return (p > 0 ? '+' : p < 0 ? '−' : '') + Math.abs(p).toLocaleString('fr-CA') + NBSP + 'pts'
}

const PER: Record<Exclude<ContributionFrequency, 'aucune'>, string> = {
  'deux-semaines': 'aux deux semaines',
  mensuelle: 'par mois',
  annuelle: 'par année',
}

/** « 100 $ par mois », ou « Aucun » si rien n'est prévu. */
export function contribution(c: Contribution): string {
  return c.frequency === 'aucune' ? 'Aucun' : `${money(c.amount)} ${PER[c.frequency]}`
}

const INSTRUMENTS: Record<string, string> = { action: 'Action', fnb: 'FNB', crypto: 'Crypto' }

/** « Action · Technologie », « FNB · Obligations gouvernementales » : type d'instrument et secteur ou catégorie. */
export function kindOf(h: Holding): string {
  return [INSTRUMENTS[h.instrument ?? ''], h.detail].filter(Boolean).join(' · ')
}

/** « 8 avr. 2025 », à partir d'une date AAAA-MM-JJ. */
export function day(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** « avr. 2025 ». */
export function monthYear(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('fr-CA', { month: 'short', year: 'numeric' })
}

/** Une valeur de preuve dans son unité : « −11,1 % », « 8,4 », « 10 ans ». */
export function evidenceValue(v: number, unit: Evidence['unit']): string {
  if (unit === 'pct') return (v < 0 ? '−' : '') + pct(Math.abs(v))
  if (unit === 'ans') return `${v.toLocaleString('fr-CA')}${NBSP}an${Math.abs(v) >= 2 ? 's' : ''}`
  return v.toLocaleString('fr-CA', { maximumFractionDigits: 1 })
}

/** Un nombre de points de pourcentage, une décimale au plus : « 5 », « 12,5 ». */
export function shareNumber(v: number): string {
  return v.toLocaleString('fr-CA', { maximumFractionDigits: 1, useGrouping: false })
}

/** Un pourcentage saisi par le client (0 à 100) : « 5 % », « 12,5 % ». */
export function share(v: number): string {
  return shareNumber(v) + NBSP + '%'
}
