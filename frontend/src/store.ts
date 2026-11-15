import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { buildAll, emptyConstraints, PORTFOLIO_META, riskScore, WINNER_META } from './lib/engine'
import type { BackendPortfolio, Constraints, ConstraintBlock, Contribution, DashboardLevel, Level, Portfolio, PortfolioId, Profile, ProfileCheck, Vehicles } from './types'

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

/** Profil cohérent : un seul portefeuille (le gagnant). Profil incohérent : les trois. */
export type Portfolios = Partial<Record<PortfolioId, Portfolio>>

export interface State {
  profile: Profile
  contribution: Contribution
  constraints: Constraints
  /** Verdict de Pépite sur le questionnaire, renvoyé au backend avec la construction. */
  check: ProfileCheck | null
  /** Ajustement écrit avant l'envoi aux gestionnaires (profil cohérent seulement). */
  adjustment: string
  /** Portefeuilles tels que construits, avant les ajustements du chat. */
  base: Portfolios | null
  portfolios: Portfolios | null
  adjustments: AppliedAdjustment[]
  disclaimerSeen: boolean
  setProfile: (patch: Partial<Profile>) => void
  setContribution: (patch: Partial<Contribution>) => void
  setLevel: (block: ConstraintBlock, id: string, level: Level) => void
  setVehicles: (vehicles: Vehicles) => void
  clearConstraints: () => void
  setCheck: (check: ProfileCheck | null) => void
  setAdjustment: (text: string) => void
  acceptDisclaimer: () => void
  /** Portefeuilles du moteur d'exemple, quand le backend n'en a pas fourni. */
  build: () => void
  setPortfolios: (received: Partial<Record<PortfolioId, BackendPortfolio>>) => void
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

/** Applique les ajustements du chat : un portefeuille ajusté est recalculé par le moteur d'exemple, les autres restent tels quels. */
function withAdjustments(base: Portfolios, score: number, c: Constraints, adjustments: Omit<AppliedAdjustment, 'id'>[]): Portfolios {
  const out: Portfolios = { ...base }
  for (const id of Object.keys(base) as PortfolioId[]) {
    const mine = adjustments.filter((a) => a.portfolio === id)
    if (!mine.length) continue
    const patched = mine.reduce((acc, a) => merge(acc, a.patch), c)
    const shift = mine.reduce((acc, a) => acc + a.riskShift, 0)
    const rebuilt = buildAll(Math.min(95, Math.max(5, score + shift)), patched)[id]
    rebuilt.agentNotes.push(...mine.filter((a) => a.label).map((a) => `Ajustement demandé : ${a.label}.`))
    out[id] = { ...rebuilt, name: base[id]!.name, tagline: base[id]!.tagline }
  }
  return out
}

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      profile: DEFAULT_PROFILE,
      contribution: DEFAULT_CONTRIBUTION,
      constraints: emptyConstraints(),
      check: null,
      adjustment: '',
      base: null,
      portfolios: null,
      adjustments: [],
      disclaimerSeen: false,
      setProfile: (patch) => set((s) => ({ profile: { ...s.profile, ...patch } })),
      setContribution: (patch) => set((s) => ({ contribution: { ...s.contribution, ...patch } })),
      setLevel: (block, id, level) =>
        set((s) => ({ constraints: { ...s.constraints, [block]: { ...s.constraints[block], [id]: level } } })),
      setVehicles: (vehicles) => set((s) => ({ constraints: { ...s.constraints, vehicles } })),
      clearConstraints: () => set({ constraints: emptyConstraints() }),
      setCheck: (check) => set({ check }),
      setAdjustment: (adjustment) => set({ adjustment }),
      acceptDisclaimer: () => set({ disclaimerSeen: true }),
      build: () =>
        set((s) => {
          const all = buildAll(riskScore(s.profile), s.constraints)
          const base: Portfolios = s.check?.coherent ? { equilibre: { ...all.equilibre, ...WINNER_META } } : all
          return { adjustments: [], base, portfolios: base }
        }),
      setPortfolios: (received) => {
        const base: Portfolios = {}
        for (const [id, p] of Object.entries(received) as [PortfolioId, BackendPortfolio][]) base[id] = { ...PORTFOLIO_META[id], ...p }
        if (Object.keys(base).length) set({ adjustments: [], base, portfolios: base })
        else get().build()
      },
      previewAdjustment: (a) => {
        const s = get()
        return withAdjustments(s.base ?? {}, riskScore(s.profile), s.constraints, [...s.adjustments, { ...a, label: '' }])[a.portfolio]!
      },
      applyAdjustment: (a) => {
        const adjustments = [...get().adjustments, { ...a, id: crypto.randomUUID() }]
        set((s) => ({ adjustments, portfolios: withAdjustments(s.base ?? {}, riskScore(s.profile), s.constraints, adjustments) }))
      },
      undoAdjustment: (id) => {
        const adjustments = get().adjustments.filter((a) => a.id !== id)
        set((s) => ({ adjustments, portfolios: withAdjustments(s.base ?? {}, riskScore(s.profile), s.constraints, adjustments) }))
      },
      reset: () =>
        set({
          profile: DEFAULT_PROFILE,
          contribution: DEFAULT_CONTRIBUTION,
          constraints: emptyConstraints(),
          check: null,
          adjustment: '',
          base: null,
          portfolios: null,
          adjustments: [],
          disclaimerSeen: false,
        }),
    }),
    { name: 'bas-de-laine', storage: createJSONStorage(() => sessionStorage) },
  ),
)
