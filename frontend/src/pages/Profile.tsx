import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { AmountInput, ChoiceCards, ChoiceList, Scale, Slider } from '../components/inputs'
import type { Pose } from '../components/Pepite'
import { QuestionShell } from '../components/QuestionShell'
import { money } from '../lib/format'
import { useApp } from '../store'
import type { Objective, Profile as P } from '../types'

interface Step {
  question: string
  hint?: string
  pose: Pose
  pepite: string
  render: (p: P, set: (patch: Partial<P>) => void) => React.ReactNode
}

const STEPS: Step[] = [
  {
    question: 'Quel âge as-tu?',
    hint: 'Ça nous aide à estimer combien de temps ton argent peut travailler.',
    pose: 'wave',
    pepite: 'Salut! On commence simple.',
    render: (p, set) => <Slider label="Ton âge" value={p.age} min={18} max={85} format={(v) => `${v} ans`} onChange={(age) => set({ age })} />,
  },
  {
    question: 'Combien veux-tu investir?',
    hint: 'Un montant approximatif suffit. Tu pourras le changer plus tard.',
    pose: 'coffee',
    pepite: 'Petit ou gros montant, chaque bas de laine compte.',
    render: (p, set) => <AmountInput value={p.amount} onChange={(amount) => set({ amount })} />,
  },
  {
    question: 'À quoi va servir cet argent?',
    hint: 'Choisis ce qui te correspond le mieux.',
    pose: 'map',
    pepite: 'Ton objectif, c’est notre boussole.',
    render: (p, set) => (
      <ChoiceCards<Objective>
        label="Objectif"
        value={p.objective}
        onChange={(objective) => set({ objective })}
        options={[
          { value: 'securiser', label: 'Sécuriser', desc: 'Préserver ce que j’ai' },
          { value: 'fructifier', label: 'Faire fructifier', desc: 'De la croissance, peu de surprises' },
          { value: 'viser-haut', label: 'Viser haut', desc: 'Miser sur la croissance à long terme' },
        ]}
      />
    ),
  },
  {
    question: 'Dans combien de temps auras-tu besoin de cet argent?',
    hint: 'Glisse pour indiquer un nombre d’années approximatif.',
    pose: 'binoculars',
    pepite: 'Plus l’horizon est loin, plus on peut patienter.',
    render: (p, set) => <Slider label="Horizon" value={p.horizon} min={1} max={30} format={(v) => (v === 1 ? '1 an' : `${v} ans`)} onChange={(horizon) => set({ horizon })} />,
  },
  {
    question: 'Ton portefeuille perd 20 % en un mois. Que fais-tu?',
    hint: 'Il n’y a pas de mauvaise réponse.',
    pose: 'surprised',
    pepite: 'Sois honnête, ça reste entre nous!',
    render: (p, set) => (
      <ChoiceList
        label="Réaction à une baisse"
        value={p.lossReaction}
        onChange={(lossReaction) => set({ lossReaction })}
        options={[
          { value: 0, label: 'Je vends tout', desc: 'Je ne veux pas perdre plus' },
          { value: 1, label: 'Je vends une partie', desc: 'Je réduis un peu le risque' },
          { value: 2, label: 'J’attends', desc: 'Les marchés finissent souvent par remonter' },
          { value: 3, label: 'J’investis plus', desc: 'Les prix sont bas, c’est le moment d’acheter' },
        ]}
      />
    ),
  },
  {
    question: 'Es-tu à l’aise avec l’investissement?',
    hint: 'De 1 (pas du tout) à 5 (très à l’aise). On adaptera les explications.',
    pose: 'thinking',
    pepite: 'Débutant ou expert, je m’adapte à toi.',
    render: (p, set) => <Scale label="Aisance" value={p.comfort} minLabel="Pas du tout" maxLabel="Très à l’aise" onChange={(comfort) => set({ comfort })} />,
  },
]

export default function Profile() {
  const { step: raw } = useParams()
  const step = Number(raw)
  const navigate = useNavigate()
  const profile = useApp((s) => s.profile)
  const setProfile = useApp((s) => s.setProfile)
  const setRiskOverride = useApp((s) => s.setRiskOverride)
  if (!(step >= 1 && step <= STEPS.length)) return <Navigate to="/profil/1" replace />
  const s = STEPS[step - 1]
  const canNext = step !== 2 || profile.amount >= 100
  return (
    <QuestionShell
      chapter="Ton profil"
      step={step}
      total={STEPS.length}
      question={s.question}
      hint={s.hint}
      pose={s.pose}
      pepite={step === 2 && profile.amount ? `${money(profile.amount)}, c’est noté.` : s.pepite}
      canNext={canNext}
      onBack={() => navigate(step === 1 ? '/' : `/profil/${step - 1}`)}
      onNext={() => {
        if (step === STEPS.length) {
          setRiskOverride(null)
          navigate('/preferences/1')
        } else navigate(`/profil/${step + 1}`)
      }}
    >
      {s.render(profile, setProfile)}
    </QuestionShell>
  )
}
