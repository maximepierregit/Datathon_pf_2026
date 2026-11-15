// Seul point de contact avec le backend. checkProfile, runPipeline et askPepite lisent le flux SSE des agents
// (backend/src/invest_agents/workflow/flow.py) ; sans backend, un script d'exemple et proposeAdjustment
// (simulé) prennent le relais.
import { CLASS_LABELS, UNIVERSE } from './data/catalog'
import { coherenceWarnings, PORTFOLIO_IDS } from './lib/engine'
import type { AdjustProposal, AgentId, AgentStatus, Constraints, Portfolio, PipelineEvent, Profile, ProfileCheck } from './types'

/** Servi par le proxy Vite en local, par nginx en ligne. */
const PIPELINE_URL = '/api/invocations'

const EVENT_TYPES = new Set<string>(['check', 'agent_status', 'pepite', 'universe', 'rerun', 'warning', 'portfolios', 'error', 'done'])

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

/** Ouvre le flux SSE des agents ; null si le backend ne répond pas (le script d'exemple prend alors le relais). */
async function openStream(body: object, signal: AbortSignal): Promise<ReadableStream<Uint8Array> | null> {
  try {
    const res = await fetch(PIPELINE_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
    if (!res.ok || !res.body || !res.headers.get('content-type')?.includes('text/event-stream')) throw new Error(`HTTP ${res.status}`)
    return res.body
  } catch (err) {
    if (signal.aborted) throw err
    console.warn('Backend indisponible, script d’exemple :', err)
    return null
  }
}

/** Relaie les événements connus ; émet `error` si le flux casse et `done` s'il s'arrête sans. */
async function relay(body: ReadableStream<Uint8Array>, onEvent: (e: PipelineEvent) => void, signal: AbortSignal) {
  let finished = false
  try {
    for await (const e of readEvents(body)) {
      if (!e || typeof e !== 'object' || !EVENT_TYPES.has((e as { type?: string }).type ?? '')) continue
      onEvent(e as PipelineEvent)
      finished ||= (e as PipelineEvent).type === 'done'
    }
  } catch (err) {
    if (signal.aborted) throw err
    console.warn('Flux des agents interrompu :', err)
    onEvent({ type: 'error', message: 'La connexion avec mes agents s’est interrompue.' })
  }
  if (!finished) onEvent({ type: 'done' })
}

/** Vérification d'exemple : les règles de coherenceWarnings() tiennent lieu de Pépite. */
function exampleCheck(score: number, constraints: Constraints): ProfileCheck {
  const warnings = coherenceWarnings(score, constraints)
  return {
    coherent: warnings.length === 0,
    summary: warnings.length ? 'Quelques-unes de tes réponses tirent dans des directions opposées.' : 'Tes réponses se tiennent : ton profil et tes préférences vont dans le même sens.',
    issues: warnings.map(({ title, detail }) => ({ title, detail })),
  }
}

/**
 * Pépite relit le questionnaire avant tout envoi aux gestionnaires.
 * `session` : la conversation ouverte côté backend (null avec la vérification d'exemple).
 * `onStep` reçoit ce que Pépite annonce faire (« Je calcule ton profil de risque… »).
 */
export async function checkProfile(
  input: { score: number; profile: Profile; constraints: Constraints },
  signal: AbortSignal,
  onStep: (text: string) => void = () => {},
): Promise<{ check: ProfileCheck; session: string | null }> {
  // Court délai : en mode strict, React monte deux fois la page ; le premier montage est annulé avant l'appel.
  await wait(50, signal)
  const body = await openStream({ mode: 'monport_check', profile: input.profile, constraints: input.constraints }, signal)
  if (!body) {
    // Assez long pour qu'on voie Pépite réfléchir.
    for (const text of ['Je calcule ton profil de risque…', 'Je cherche les contradictions dans tes réponses…']) {
      await wait(1300, signal)
      onStep(text)
    }
    await wait(1300, signal)
    return { check: exampleCheck(input.score, input.constraints), session: null }
  }
  let check: ProfileCheck | null = null
  let session: string | null = null
  await relay(body, (e) => {
    if (e.type === 'agent_status' && e.agent === 'pepite') onStep(e.message)
    if (e.type === 'check') {
      check = e.check
      session = e.session ?? null
    }
  }, signal)
  return check ? { check, session } : { check: exampleCheck(input.score, input.constraints), session: null }
}

type PipelineInput = { score: number; profile: Profile; constraints: Constraints; check: ProfileCheck; adjustment: string; session: string | null }

export async function runPipeline(input: PipelineInput, onEvent: (e: PipelineEvent) => void, signal: AbortSignal) {
  await wait(50, signal)
  const { profile, constraints, check, adjustment, session } = input
  const body = await openStream({ mode: 'monport', profile, constraints, check, adjustment, session }, signal)
  if (!body) return runScript(input, onEvent, signal)
  await relay(body, onEvent, signal)
}

/**
 * Message du client à Pépite, une fois les portefeuilles construits. Elle interroge au besoin ses agents et peut
 * relancer une construction (nouvel événement `portfolios`). Retourne false si le backend ne répond pas.
 */
export async function askPepite(session: string, message: string, onEvent: (e: PipelineEvent) => void, signal: AbortSignal): Promise<boolean> {
  const body = await openStream({ mode: 'monport_chat', session, message }, signal)
  if (!body) return false
  await relay(body, onEvent, signal)
  return true
}

/**
 * Le client a confirmé les changements convenus dans le chat : Pépite relance toute la construction. Mêmes événements
 * que runPipeline. Retourne false si le backend ne répond pas.
 */
export async function rebuildPipeline(session: string, onEvent: (e: PipelineEvent) => void, signal: AbortSignal): Promise<boolean> {
  // Même court délai que runPipeline : le backend consomme la demande, le premier montage du mode strict ne doit pas l'envoyer.
  await wait(50, signal)
  const body = await openStream({ mode: 'monport_rebuild', session }, signal)
  if (!body) return false
  await relay(body, onEvent, signal)
  return true
}

async function runScript(input: PipelineInput, onEvent: (e: PipelineEvent) => void, signal: AbortSignal) {
  const excluded = Object.values(input.constraints.themes).filter((v) => v === 'exclure').length
  const classesOut = Object.values(input.constraints.classes).filter((v) => v === 'exclure').length
  const after = UNIVERSE.length * 7 - excluded * 9 - classesOut * 6
  const coherent = input.check.coherent

  const status = (agent: AgentId, s: AgentStatus, message: string): PipelineEvent => ({ type: 'agent_status', agent, status: s, message })
  // Les trois gestionnaires, puis les trois juges, travaillent en parallèle : leurs étapes sont décalées.
  const each = (role: 'gestionnaire' | 'juge', s: AgentStatus, message: string, delay: number): [number, PipelineEvent][] =>
    PORTFOLIO_IDS.map((id, i) => [i ? 250 : delay, status(`${role}-${id}`, s, message)])
  // Profil cohérent : le juge final garde un gagnant. Profil incohérent : Pépite mélange les bases 80/20.
  const finale: [number, PipelineEvent][] = coherent
    ? [
        [400, status('juge-final', 'running', 'Comparaison des 3 portefeuilles…')],
        [1500, status('juge-final', 'done', 'La variante fidèle l’emporte.')],
      ]
    : [[500, status('pepite', 'done', 'Mélanges 80/20 prêts : profil d’abord, préférences d’abord.')]]

  const script: [number, PipelineEvent][] = [
    [300, { type: 'pepite', text: 'C’est parti! J’écris les consignes de tes trois gestionnaires.' }],
    [300, status('pepite', 'running', 'J’écris les 3 profils de contraintes…')],
    [1600, { type: 'universe', before: UNIVERSE.length * 7, after }],
    [500, status('pepite', 'done', '3 profils de contraintes envoyés aux gestionnaires.')],
    ...each('gestionnaire', 'running', 'Recherche de placements…', 400),
    ...each('gestionnaire', 'running', 'Calcul des poids…', 1400),
    ...each('gestionnaire', 'done', 'Portefeuille prêt.', 1200),
    ...each('juge', 'running', 'Vérification de tes limites…', 400),
    ...each('juge', 'done', 'Toutes tes limites sont respectées.', 1300),
    ...finale,
    [400, status('risques', 'running', 'Recherche des incohérences avec ton profil…')],
    [1300, status('risques', 'done', 'Rien de particulier à signaler.')],
    [500, { type: 'pepite', text: coherent ? 'Voilà! Ton portefeuille t’attend.' : 'Voilà! Trois propositions t’attendent. C’est toi qui choisis.' }],
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
    reply: (p) => `<p>D’accord! J’ajoute une part de <strong>FNB technologie</strong> au portefeuille « ${p.name} », prise sur les actions régionales.</p>`,
    patch: { themes: { tech: 30 } },
    diff: [{ label: 'FNB technologie', get: tickerWeight('THM-TEC') }],
  },
  {
    match: /pétrole|petrole|fossile|énergie trad/i,
    reply: () => '<p>C’est noté : <strong>j’exclus les énergies fossiles</strong>.</p><astuce>Les FNB concernés sont retirés, et ton niveau de risque bouge à peine.</astuce>',
    patch: { themes: { fossiles: 'exclure' } },
    diff: [{ label: 'FNB énergie traditionnelle', get: tickerWeight('THM-ENR') }],
  },
  {
    match: /crypto|bitcoin/i,
    reply: (p) => `<p>Je peux augmenter la <strong>crypto</strong> dans le portefeuille « ${p.name} ». Voici ce que ça donnerait.</p>`,
    patch: { classes: { crypto: 10 } },
    warning: (score) => (score < 50 ? 'ça augmente ton risque au-delà de ton profil. Tu peux quand même l’appliquer, c’est ton choix.' : undefined),
    diff: [{ label: CLASS_LABELS.crypto, get: (q) => q.allocation.crypto }],
  },
  {
    match: /moins de risque|prudent|sécur|stable/i,
    reply: () => '<p>Je réduis les placements les plus agités au profit des <strong>obligations</strong>.</p><astuce>Ton portefeuille bougera moins, mais il grandira aussi un peu moins vite.</astuce>',
    patch: { classes: { crypto: 'exclure' } },
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
      reply: `<p>Je ne comprends pas encore bien ta demande pour le portefeuille « ${p.name} ». Essaie par exemple :</p><ul><li>plus de tech</li><li>pas de pétrole</li><li>moins de risque</li></ul>`,
      changes: [],
    }
  }
  const next = preview(rule.patch ?? {}, rule.riskShift ?? 0)
  const changes = rule.diff
    .map((d) => ({ label: d.label, before: d.get(p), after: d.get(next) }))
    .filter((c) => Math.abs(c.after - c.before) >= 0.001)
  if (!changes.length) return { reply: `<p>C’est déjà le cas dans le portefeuille « ${p.name} » : <strong>rien à changer</strong>.</p>`, changes: [] }
  return { reply: rule.reply(p), changes, warning: rule.warning?.(score), patch: rule.patch, riskShift: rule.riskShift }
}
