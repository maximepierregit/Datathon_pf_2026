import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { buildAll, emptyConstraints, riskScore } from './lib/engine'
import type { Constraints, ConstraintBlock, Contribution, DashboardLevel, Level, Portfolio, PortfolioId, Profile, Vehicles } from './types'

export const DEFAULT_PROFILE: Profile = {
  age: 35,
  amount: 10000,
  objective: 'fructifier',
  horizon: 12,
  lossReaction: 2,
  comfort: 3,
}

export const DEFAULT_CONTRIBUTION: Contribution = { frequency: 'aucune', amount: 100 }

export interface AppliedAdjustment {
  id: string
  portfolio: PortfolioId
  label: string
  patch: Partial<Constraints>
  riskShift: number
}

export interface State {
  profile: Profile
  contribution: Contribution
  constraints: Constraints
  portfolios: Record<PortfolioId, Portfolio> | null
  adjustments: AppliedAdjustment[]
  disclaimerSeen: boolean
  setProfile: (patch: Partial<Profile>) => void
  setContribution: (patch: Partial<Contribution>) => void
  setLevel: (block: ConstraintBlock, id: string, level: Level) => void
  setVehicles: (vehicles: Vehicles) => void
  clearConstraints: () => void
  acceptDisclaimer: () => void
  build: () => void
  /** Portefeuille tel qu'il serait avec cet ajustement en plus, sans l'appliquer. */
  previewAdjustment: (a: Omit<AppliedAdjustment, 'id' | 'label'>) => Portfolio
  applyAdjustment: (a: Omit<AppliedAdjustment, 'id'>) => void
  undoAdjustment: (id: string) => void
  reset: () => void
}

export function defaultDashboardLevel(comfort: number): DashboardLevel {
  return comfort <= 2 ? 'debutant' : comfort === 3 ? 'intermediaire' : 'avance'
}

function merge(base: Constraints, patch: Partial<Constraints>): Constraints {
  const out = structuredClone(base)
  for (const k of Object.keys(patch) as ConstraintBlock[]) Object.assign(out[k], patch[k])
  return out
}

/** Reconstruit les 3 portefeuilles en appliquant les ajustements de chacun. */
function rebuild(score: number, c: Constraints, adjustments: AppliedAdjustment[]) {
  const all = buildAll(score, c)
  for (const id of Object.keys(all) as PortfolioId[]) {
    const mine = adjustments.filter((a) => a.portfolio === id)
    if (!mine.length) continue
    const patched = mine.reduce((acc, a) => merge(acc, a.patch), c)
    const shift = mine.reduce((acc, a) => acc + a.riskShift, 0)
    const rebuilt = buildAll(Math.min(95, Math.max(5, score + shift)), patched)[id]
    rebuilt.agentNotes.push(...mine.map((a) => `Ajustement demandé : ${a.label}.`))
    all[id] = rebuilt
  }
  return all
}

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      profile: DEFAULT_PROFILE,
      contribution: DEFAULT_CONTRIBUTION,
      constraints: emptyConstraints(),
      portfolios: null,
      adjustments: [],
      disclaimerSeen: false,
      setProfile: (patch) => set((s) => ({ profile: { ...s.profile, ...patch } })),
      setContribution: (patch) => set((s) => ({ contribution: { ...s.contribution, ...patch } })),
      setLevel: (block, id, level) =>
        set((s) => ({ constraints: { ...s.constraints, [block]: { ...s.constraints[block], [id]: level } } })),
      setVehicles: (vehicles) => set((s) => ({ constraints: { ...s.constraints, vehicles } })),
      clearConstraints: () => set({ constraints: emptyConstraints() }),
      acceptDisclaimer: () => set({ disclaimerSeen: true }),
      build: () => set((s) => ({ adjustments: [], portfolios: rebuild(riskScore(s.profile), s.constraints, []) })),
      previewAdjustment: (a) => {
        const s = get()
        return rebuild(riskScore(s.profile), s.constraints, [...s.adjustments, { ...a, id: 'preview', label: '' }])[a.portfolio]
      },
      applyAdjustment: (a) => {
        const adjustments = [...get().adjustments, { ...a, id: crypto.randomUUID() }]
        set((s) => ({ adjustments, portfolios: rebuild(riskScore(s.profile), s.constraints, adjustments) }))
      },
      undoAdjustment: (id) => {
        const adjustments = get().adjustments.filter((a) => a.id !== id)
        set((s) => ({ adjustments, portfolios: rebuild(riskScore(s.profile), s.constraints, adjustments) }))
      },
      reset: () =>
        set({ profile: DEFAULT_PROFILE, contribution: DEFAULT_CONTRIBUTION, constraints: emptyConstraints(), portfolios: null, adjustments: [], disclaimerSeen: false }),
    }),
    { name: 'bas-de-laine', storage: createJSONStorage(() => sessionStorage) },
  ),
)
