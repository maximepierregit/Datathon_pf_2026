import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { CheckCard, PreferenceTuner } from '../components/inputs'
import type { Pose } from '../components/Pepite'
import { QuestionShell } from '../components/QuestionShell'
import { Alert } from '../components/ui'
import { BLOCKS } from '../data/catalog'
import { coherenceWarnings, isFnbOnly, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { ConstraintBlock } from '../types'

const POSES: Record<ConstraintBlock, Pose> = { classes: 'laptop', regions: 'map', themes: 'question', factors: 'cool' }
const PEPITE: Record<ConstraintBlock, string> = {
  classes: 'Tout à « Neutre »? Parfait, je choisis pour toi.',
  regions: 'Le monde est grand : on peut tout couvrir.',
  themes: 'Tes valeurs comptent autant que les chiffres.',
  factors: 'Tu es à l’aise : voici des réglages d’initié.',
}

/** Les facteurs ne s'affichent que pour une aisance de 4 ou 5. */
function preferenceBlocks(comfort: number): ConstraintBlock[] {
  return comfort >= 4 ? ['classes', 'regions', 'themes', 'factors'] : ['classes', 'regions', 'themes']
}

export default function Preferences() {
  const { step: raw } = useParams()
  const step = Number(raw)
  const navigate = useNavigate()
  const state = useApp()
  const blocks = preferenceBlocks(state.profile.comfort)
  if (!(step >= 1 && step <= blocks.length)) return <Navigate to="/preferences/1" replace />
  const block = blocks[step - 1]
  const def = BLOCKS[block]
  const warnings = block === 'classes' ? coherenceWarnings(riskScore(state.profile), state.constraints) : []
  const fnbOnly = block === 'classes' && isFnbOnly(state.constraints)
  const last = step === blocks.length
  return (
    <QuestionShell
      chapter="Tes préférences"
      step={step}
      total={blocks.length}
      question={def.title}
      hint={def.hint}
      pose={warnings.length ? 'thinking' : POSES[block]}
      pepite={warnings.length ? 'Hmm, quelque chose cloche…' : fnbOnly ? 'Que des FNB? Simple et bien diversifié, j’aime ça.' : PEPITE[block]}
      canNext
      nextLabel={last ? 'Lancer la construction' : 'Continuer'}
      onBack={() => navigate(step === 1 ? '/transition' : `/preferences/${step - 1}`)}
      onNext={() => navigate(last ? '/construction' : `/preferences/${step + 1}`)}
      aside={
        warnings.length > 0 && (
          <div className="flex flex-col gap-2">
            {warnings.map((w) => (
              <Alert key={w} title="Pépite te prévient">
                {w} On construira quand même ce que tu demandes, avec un avertissement.
              </Alert>
            ))}
          </div>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {block === 'classes' && (
          <CheckCard
            checked={fnbOnly}
            onChange={state.setFnbOnly}
            label="FNB seulement"
            desc="Aucun titre en direct. Ton portefeuille couvre quand même actions, obligations et le reste, mais seulement par des FNB."
          />
        )}
        <PreferenceTuner items={def.items} value={state.constraints[block]} onChange={(id, l) => state.setLevel(block, id, l)} />
      </div>
    </QuestionShell>
  )
}
