// Seul point de contact avec le backend. runPipeline lit le flux SSE du pipeline Strands
// et rejoue le script d'exemple si le backend ne répond pas ; proposeAdjustment reste simulé.
import { CLASS_LABELS, UNIVERSE } from './data/catalog'
import { coherenceWarnings, PORTFOLIO_IDS, PORTFOLIO_META } from './lib/engine'
import type { AdjustProposal, AgentId, AgentStatus, Constraints, Portfolio, PipelineEvent, Profile } from './types'

/** Servi par le proxy Vite en local, par nginx en ligne. */
const PIPELINE_URL = '/api/invocations'

const EVENT_TYPES = new Set<string>(['agent_status', 'pepite', 'universe', 'rerun', 'warning', 'portfolios', 'error', 'done'])

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    })
  })

/** Découpe un flux text/event-stream en objets JSON, un par bloc `data:`. */
async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value.replace(/\r\n/g, '\n')
    let end
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const data = buffer
        .slice(0, end)
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart())
        .join('\n')
      buffer = buffer.slice(end + 2)
      if (data) yield JSON.parse(data)
    }
  }
}

type PipelineInput = { score: number; profile: Profile; constraints: Constraints }

export async function runPipeline(input: PipelineInput, onEvent: (e: PipelineEvent) => void, signal: AbortSignal) {
  // Court délai : en mode strict, React monte deux fois la page ; le premier montage est annulé avant l'appel.
  await wait(50, signal)
  let body: ReadableStream<Uint8Array>
  try {
    const res = await fetch(PIPELINE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'monport', profile: input.profile, constraints: input.constraints }),
      signal,
    })
    if (!res.ok || !res.body || !res.headers.get('content-type')?.includes('text/event-stream')) throw new Error(`HTTP ${res.status}`)
    body = res.body
  } catch (err) {
    if (signal.aborted) throw err
    console.warn('Backend indisponible, pipeline d’exemple :', err)
    return runScript(input, onEvent, signal)
  }

  let finished = false
  try {
    for await (const e of readEvents(body)) {
      if (!e || typeof e !== 'object' || !EVENT_TYPES.has((e as { type?: string }).type ?? '')) continue
      onEvent(e as PipelineEvent)
      finished ||= (e as PipelineEvent).type === 'done'
    }
  } catch (err) {
    if (signal.aborted) throw err
    console.warn('Flux du pipeline interrompu :', err)
    onEvent({ type: 'error', message: 'La connexion avec mes agents s’est interrompue.' })
  }
  if (!finished) onEvent({ type: 'done' })
}

async function runScript(input: PipelineInput, onEvent: (e: PipelineEvent) => void, signal: AbortSignal) {
  const excluded = Object.values(input.constraints.themes).filter((l) => l === -2).length
  const classesOut = Object.values(input.constraints.classes).filter((l) => l === -2).length
  const after = UNIVERSE.length * 7 - excluded * 9 - classesOut * 6
  const warnings = coherenceWarnings(input.score, input.constraints)

  const status = (agent: AgentId, s: AgentStatus, message: string): PipelineEvent => ({ type: 'agent_status', agent, status: s, message })
  // Les trois gestionnaires, puis les trois juges, travaillent en parallèle : leurs étapes sont décalées.
  const each = (role: 'gestionnaire' | 'juge', s: AgentStatus, message: string, delay: number): [number, PipelineEvent][] =>
    PORTFOLIO_IDS.map((id, i) => [i ? 250 : delay, status(`${role}-${id}`, s, message)])

  const script: [number, PipelineEvent][] = [
    [300, { type: 'pepite', text: 'C’est parti! Mes agents se mettent au travail.' }],
    [500, status('profil', 'running', 'Lecture de ton profil et de tes préférences…')],
    [1600, { type: 'universe', before: UNIVERSE.length * 7, after }],
    [700, status('profil', 'done', `${after} placements retenus sur ${UNIVERSE.length * 7}.`)],
    ...each('gestionnaire', 'running', 'Recherche de placements…', 400),
    ...each('gestionnaire', 'running', 'Calcul des poids…', 1400),
    ...each('gestionnaire', 'done', 'Portefeuille prêt.', 1200),
    ...each('juge', 'running', 'Vérification de tes limites…', 400),
    [1200, status('juge-prudent', 'done', 'Toutes tes limites sont respectées.')],
    [300, status('juge-equilibre', 'done', 'Toutes tes limites sont respectées.')],
    [600, { type: 'rerun', portfolio: 'conviction', reason: 'trop concentré sur une seule région. Je le renvoie au gestionnaire.' }],
    [1600, status('gestionnaire-conviction', 'done', 'Portefeuille recalculé : la concentration est corrigée.')],
    [700, status('juge-conviction', 'done', 'Toutes tes limites sont respectées.')],
    [400, status('risques', 'running', 'Recherche des incohérences avec ton profil…')],
    ...warnings.map((text): [number, PipelineEvent] => [900, { type: 'warning', text }]),
    [1000, status('risques', 'done', warnings.length ? `${warnings.length} mise(s) en garde à lire.` : 'Rien de particulier à signaler.')],
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
