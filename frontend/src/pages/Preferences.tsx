import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { ChoiceList, PreferenceTuner, type Option } from '../components/inputs'
import type { Pose } from '../components/Pepite'
import { QuestionShell } from '../components/QuestionShell'
import { Alert } from '../components/ui'
import { BLOCKS } from '../data/catalog'
import { coherenceWarnings, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { ConstraintBlock, Vehicles } from '../types'

/** Le véhicule (FNB ou non) passe avant les blocs à 5 niveaux. */
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
  title: 'Veux-tu investir seulement dans des FNB?',
  hint: 'Un FNB (fonds négocié en bourse) regroupe des dizaines de titres en un seul placement. Il peut contenir des actions, des obligations, de l’or…',
}

const VEHICLE_OPTIONS: Option<Vehicles>[] = [
  { value: 'fnb', label: 'FNB seulement', desc: 'Simple et diversifié. Ton portefeuille couvre quand même actions, obligations et le reste, mais toujours par des FNB.' },
  { value: 'tous', label: 'FNB et titres individuels', desc: 'Les agents peuvent aussi choisir des actions ou des obligations à l’unité.' },
]

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
  const warnings = s === 'classes' ? coherenceWarnings(riskScore(state.profile, state.contribution), state.constraints) : []
  const fnbOnly = s === 'vehicles' && state.constraints.vehicles === 'fnb'
  const last = step === steps.length
  return (
    <QuestionShell
      chapter="Tes préférences"
      step={step}
      total={steps.length}
      question={def.title}
      hint={def.hint}
      pose={warnings.length ? 'thinking' : POSES[s]}
      pepite={warnings.length ? 'Hmm, quelque chose cloche…' : fnbOnly ? 'Que des FNB? Simple et bien diversifié, j’aime ça.' : PEPITE[s]}
      canNext
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
        <ChoiceList label="FNB seulement ou non"options={VEHICLE_OPTIONS} value={state.constraints.vehicles} onChange={state.setVehicles} />
      ) : (
        <PreferenceTuner items={BLOCKS[s].items} value={state.constraints[s]} onChange={(id, l) => state.setLevel(s, id, l)} />
      )}
    </QuestionShell>
  )
}
