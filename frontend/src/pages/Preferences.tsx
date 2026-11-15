import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { ChoiceList, ChoicePills, PreferenceTuner, ShareTotal, ShareTuner, type Option } from '../components/inputs'
import type { Pose } from '../components/Pepite'
import { QuestionShell } from '../components/QuestionShell'
import { Alert } from '../components/ui'
import { BLOCKS, CLASS_LABELS, sharesValid, shownClasses, THEME_PRESETS } from '../data/catalog'
import { coherenceWarnings, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { ConstraintBlock, Share, Vehicles } from '../types'

/** Le véhicule (FNB ou non) passe avant les blocs. Classes, régions, thématiques : Exclure, Neutre ou %. Facteurs : 5 niveaux. */
type PrefStep = 'vehicles' | ConstraintBlock

const POSES: Record<PrefStep, Pose> = { vehicles: 'happy', classes: 'laptop', regions: 'map', themes: 'question', factors: 'cool' }
const PEPITE: Record<PrefStep, string> = {
  vehicles: 'Un FNB, c’est un panier de titres tout fait.',
  classes: 'Tout à « Neutre »? Parfait, je choisis pour toi.',
  regions: 'Le monde est grand : on peut tout couvrir.',
  themes: 'Tes valeurs comptent autant que les chiffres.',
  factors: 'Tu es à l’aise : voici des réglages d’initié.',
}

const VEHICLES = {
  title: 'FNB, titres individuels ou les deux?',
  hint: 'Un FNB (fonds négocié en bourse) regroupe des dizaines de titres en un seul placement. Il peut contenir des actions, des obligations, de l’or…',
}

const VEHICLE_OPTIONS: Option<Vehicles>[] = [
  { value: 'fnb', label: 'FNB seulement', desc: 'Simple et diversifié. Ton portefeuille couvre quand même actions, obligations et le reste, mais toujours par des FNB.' },
  { value: 'tous', label: 'FNB et titres individuels', desc: 'Les agents peuvent aussi choisir des actions à l’unité.' },
  { value: 'titres', label: 'Titres individuels seulement', desc: 'Des actions et des cryptos détenues en direct, sans FNB. Tu sais exactement ce que tu détiens, mais il n’y aura pas d’obligations.' },
]

const VEHICLE_PEPITE: Partial<Record<Vehicles, string>> = {
  fnb: 'Que des FNB? Simple et bien diversifié, j’aime ça.',
  titres: 'Que des titres? Tu verras chaque entreprise que tu détiens.',
}

/** Le modèle de thématiques en cours : celui qui, appliqué maintenant, ne changerait rien. */
function activePreset(themes: Record<string, Share>): string | undefined {
  const same = (a: Record<string, Share>, b: Record<string, Share>) =>
    Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => b[k] === v)
  return THEME_PRESETS.find((p) => same(p.apply(themes), themes))?.id
}

/** Les facteurs ne s'affichent que pour une aisance de 4 ou 5. */
function preferenceSteps(comfort: number): PrefStep[] {
  return comfort >= 4 ? ['vehicles', 'classes', 'regions', 'themes', 'factors'] : ['vehicles', 'classes', 'regions', 'themes']
}

export default function Preferences() {
  const { step: raw } = useParams()
  const step = Number(raw)
  const navigate = useNavigate()
  const state = useApp()
  const steps = preferenceSteps(state.profile.comfort)
  if (!(step >= 1 && step <= steps.length)) return <Navigate to="/preferences/1" replace />
  const s = steps[step - 1]
  const def = s === 'vehicles' ? VEHICLES : BLOCKS[s]
  const c = state.constraints
  const warnings = s === 'classes' ? coherenceWarnings(riskScore(state.profile), c) : []
  const vehicleSay = s === 'vehicles' ? VEHICLE_PEPITE[c.vehicles] : undefined
  const items = s === 'classes' ? shownClasses(c.vehicles).map((id) => ({ id, label: CLASS_LABELS[id] })) : s === 'vehicles' ? [] : BLOCKS[s].items
  const ids = items.map((it) => it.id)
  // Un FNB ne dit pas son pays ni son secteur : en FNB seulement, régions et thématiques ne prennent pas de pourcentage.
  const percent = s === 'classes' || c.vehicles !== 'fnb'
  const share = s === 'classes' || s === 'regions' || s === 'themes'
  const noneKept = s === 'classes' && ids.every((id) => c.classes[id] === 'exclure')
  const valid = !share || (sharesValid(c[s], ids) && !noneKept)
  const preset = s === 'themes' ? activePreset(c.themes) : undefined
  const last = step === steps.length
  return (
    <QuestionShell
      chapter="Tes préférences"
      step={step}
      total={steps.length}
      question={def.title}
      hint={share && !percent ? 'Exclus ce que tu ne veux pas. Ce que tu laisses « Neutre » reste libre.' : def.hint}
      pose={warnings.length ? 'thinking' : POSES[s]}
      pepite={warnings.length ? 'Hmm, quelque chose cloche…' : (vehicleSay ?? PEPITE[s])}
      canNext={valid}
      nextLabel={last ? 'Lancer la construction' : 'Continuer'}
      onBack={() => navigate(step === 1 ? '/transition' : `/preferences/${step - 1}`)}
      onNext={() => navigate(last ? '/verification' : `/preferences/${step + 1}`)}
      aside={
        warnings.length > 0 && (
          <div className="flex flex-col gap-2">
            {warnings.map((w) => (
              <Alert key={w.title} title="Pépite te prévient">
                {w.detail} On construira quand même ce que tu demandes, avec un avertissement.
              </Alert>
            ))}
          </div>
        )
      }
    >
      {s === 'vehicles' ? (
        <ChoiceList label="FNB, titres individuels ou les deux" options={VEHICLE_OPTIONS} value={c.vehicles} onChange={state.setVehicles} />
      ) : s === 'factors' ? (
        <PreferenceTuner items={BLOCKS.factors.items} value={c.factors} onChange={state.setFactor} />
      ) : (
        <div className="flex flex-col gap-6">
          {s === 'themes' && percent && (
            <div className="flex flex-col items-center gap-3">
              <ChoicePills
                label="Modèle de thématiques"
                options={THEME_PRESETS.map((p) => ({ value: p.id, label: p.label }))}
                value={preset}
                onChange={(id) => state.setShares('themes', THEME_PRESETS.find((p) => p.id === id)!.apply(c.themes))}
              />
              <p className="m-0 text-center text-base text-ink-soft">
                {THEME_PRESETS.find((p) => p.id === preset)?.desc ?? 'Choisis un modèle, ou règle chaque thématique toi-même.'}
              </p>
            </div>
          )}
          <ShareTuner items={items} value={c[s]} onChange={(id, v) => state.setShare(s, id, v)} percent={percent} />
          {percent ? (
            <ShareTotal value={c[s]} ids={ids} />
          ) : (
            <p className="m-0 text-center text-base text-ink-soft">
              Avec des FNB seulement, tu peux exclure ou laisser neutre : un FNB ne dit pas précisément dans quels pays ou secteurs il investit.
            </p>
          )}
          {noneKept && <p className="m-0 text-center text-base font-semibold text-red-dark">Garde au moins un type de placement.</p>}
        </div>
      )}
    </QuestionShell>
  )
}
