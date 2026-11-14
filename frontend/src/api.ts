// Seul point de contact avec le backend. Pour l'instant tout est simulé ;
// au branchement de Strands, on remplace ces deux fonctions par le flux SSE et l'appel HTTP.
import { CLASS_LABELS, UNIVERSE } from './data/catalog'
import { coherenceWarnings, PORTFOLIO_META } from './lib/engine'
import type { AdjustProposal, Constraints, Portfolio, PipelineEvent } from './types'

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    })
  })

export async function runPipeline(
  input: { score: number; constraints: Constraints },
  onEvent: (e: PipelineEvent) => void,
  signal: AbortSignal,
) {
  const excluded = Object.values(input.constraints.themes).filter((l) => l === -2).length
  const classesOut = Object.values(input.constraints.classes).filter((l) => l === -2).length
  const after = UNIVERSE.length * 7 - excluded * 9 - classesOut * 6
  const warnings = coherenceWarnings(input.score, input.constraints)

  const script: [number, PipelineEvent][] = [
    [300, { type: 'pepite', text: 'C’est parti! Mes trois agents se mettent au travail.' }],
    [500, { type: 'agent_status', agent: 'eclaireur', status: 'running', message: 'Lecture de ton profil et de tes préférences…' }],
    [1600, { type: 'universe', before: UNIVERSE.length * 7, after }],
    [900, { type: 'agent_status', agent: 'eclaireur', status: 'done', message: `${after} placements retenus sur ${UNIVERSE.length * 7}.` }],
    [400, { type: 'agent_status', agent: 'compositeur', status: 'running', message: 'Traduction de tes réponses en 3 ensembles de contraintes…' }],
    [1800, { type: 'agent_status', agent: 'compositeur', status: 'running', message: 'Optimisation des portefeuilles Prudent, Équilibré et Conviction…' }],
    [1600, { type: 'agent_status', agent: 'compositeur', status: 'done', message: '3 portefeuilles calculés.' }],
    [400, { type: 'agent_status', agent: 'verificateur', status: 'running', message: 'Relecture de chaque portefeuille…' }],
    [1400, { type: 'rerun', portfolio: 'conviction', reason: 'trop concentré sur une seule région. Je le renvoie au Compositeur.' }],
    [1600, { type: 'agent_status', agent: 'verificateur', status: 'running', message: 'Portefeuille Conviction recalculé : la concentration est corrigée.' }],
    ...warnings.map((text): [number, PipelineEvent] => [900, { type: 'warning', text }]),
    [1000, { type: 'agent_status', agent: 'verificateur', status: 'done', message: 'Tout est cohérent avec les limites de sécurité.' }],
    [500, { type: 'pepite', text: 'Voilà! Trois propositions t’attendent. C’est toi qui choisis.' }],
    [300, { type: 'done' }],
  ]
  for (const [delay, event] of script) {
    await wait(delay, signal)
    onEvent(event)
  }
}

type Preview = (patch: Partial<Constraints>, riskShift: number) => Portfolio

interface Rule {
  match: RegExp
  reply: (p: Portfolio) => string
  patch?: Partial<Constraints>
  riskShift?: number
  warning?: (score: number) => string | undefined
  /** Ce qu'on compare avant / après, sur le vrai recalcul. */
  diff: { label: string; get: (q: Portfolio) => number }[]
}

const tickerWeight = (ticker: string) => (q: Portfolio) => q.holdings.find((h) => h.ticker === ticker)?.weight ?? 0

const RULES: Rule[] = [
  {
    match: /tech|technolog/i,
    reply: (p) => `D’accord! J’ajoute une part de FNB technologie au portefeuille ${p.name}, prise sur les actions régionales.`,
    patch: { themes: { tech: 2 } },
    diff: [{ label: 'FNB technologie', get: tickerWeight('THM-TEC') }],
  },
  {
    match: /pétrole|petrole|fossile|énergie trad/i,
    reply: () => 'C’est noté : j’exclus les énergies fossiles. Les FNB concernés sont filtrés, le risque bouge à peine.',
    patch: { themes: { fossiles: -2 } },
    diff: [{ label: 'FNB énergie traditionnelle', get: tickerWeight('THM-ENR') }],
  },
  {
    match: /crypto|bitcoin/i,
    reply: (p) => `Je peux augmenter la crypto dans le portefeuille ${p.name}. Voici ce que ça donnerait.`,
    patch: { classes: { crypto: 2 } },
    warning: (score) => (score < 50 ? 'ça augmente ton risque au-delà de ton profil. Tu peux quand même l’appliquer, c’est ton choix.' : undefined),
    diff: [{ label: CLASS_LABELS.crypto, get: (q) => q.allocation.crypto }],
  },
  {
    match: /moins de risque|prudent|sécur|stable/i,
    reply: () => 'Je réduis les placements les plus volatils au profit des obligations pour adoucir les variations.',
    patch: { classes: { crypto: -1, actions: -1, obligations: 1 } },
    riskShift: -15,
    diff: [
      { label: CLASS_LABELS.actions, get: (q) => q.allocation.actions },
      { label: CLASS_LABELS.crypto, get: (q) => q.allocation.crypto },
      { label: CLASS_LABELS.obligations, get: (q) => q.allocation.obligations },
    ],
  },
]

export async function proposeAdjustment(p: Portfolio, message: string, score: number, preview: Preview): Promise<AdjustProposal> {
  await new Promise((r) => setTimeout(r, 900))
  const rule = RULES.find((r) => r.match.test(message))
  if (!rule) {
    return {
      reply: `Je ne comprends pas encore bien ta demande. Essaie par exemple « plus de tech », « pas de pétrole » ou « moins de risque » pour le portefeuille ${PORTFOLIO_META[p.id].name}.`,
      changes: [],
    }
  }
  const next = preview(rule.patch ?? {}, rule.riskShift ?? 0)
  const changes = rule.diff
    .map((d) => ({ label: d.label, before: d.get(p), after: d.get(next) }))
    .filter((c) => Math.abs(c.after - c.before) >= 0.001)
  if (!changes.length) return { reply: `C’est déjà le cas dans le portefeuille ${p.name} : rien à changer.`, changes: [] }
  return { reply: rule.reply(p), changes, warning: rule.warning?.(score), patch: rule.patch, riskShift: rule.riskShift }
}
