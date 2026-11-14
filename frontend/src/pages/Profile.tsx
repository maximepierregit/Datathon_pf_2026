import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { AmountInput, ChoiceCards, ChoiceList, ChoicePills, Scale, Slider, type Option } from '../components/inputs'
import type { Pose } from '../components/Pepite'
import { QuestionShell } from '../components/QuestionShell'
import { contribution, money } from '../lib/format'
import { useApp, type State } from '../store'
import type { ContributionFrequency, Objective } from '../types'

type Answers = Pick<State, 'profile' | 'setProfile' | 'contribution' | 'setContribution'>

interface Step {
  question: string
  hint?: string
  pose: Pose
  pepite: string | ((a: Answers) => string)
  canNext?: (a: Answers) => boolean
  render: (a: Answers) => React.ReactNode
}

const FREQUENCIES: Option<ContributionFrequency>[] = [
  { value: 'aucune', label: 'Pas prévu' },
  { value: 'deux-semaines', label: 'Aux 2 semaines' },
  { value: 'mensuelle', label: 'Chaque mois' },
  { value: 'annuelle', label: 'Chaque année' },
]

const STEPS: Step[] = [
  {
    question: 'Quel âge as-tu?',
    hint: 'Ça nous aide à estimer combien de temps ton argent peut travailler.',
    pose: 'wave',
    pepite: 'Salut! On commence simple.',
    render: ({ profile: p, setProfile: set }) => <Slider label="Ton âge" value={p.age} min={18} max={85} format={(v) => `${v} ans`} onChange={(age) => set({ age })} />,
  },
  {
    question: 'Combien veux-tu investir?',
    hint: 'Un montant approximatif suffit. Tu pourras le changer plus tard.',
    pose: 'coffee',
    pepite: ({ profile: p }) => (p.amount ? `${money(p.amount)}, c’est noté.` : 'Petit ou gros montant, chaque bas de laine compte.'),
    canNext: ({ profile: p }) => p.amount >= 100,
    render: ({ profile: p, setProfile: set }) => <AmountInput value={p.amount} onChange={(amount) => set({ amount })} />,
  },
  {
    question: 'Prévois-tu d’ajouter de l’argent plus tard?',
    hint: 'À quelle fréquence, et combien à chaque fois. Ça sert seulement à projeter ton portefeuille dans le temps.',
    pose: 'question',
    pepite: ({ contribution: c }) => (c.frequency === 'aucune' ? 'Pas de souci, on part de ton montant de départ.' : `${contribution(c)}, c’est noté.`),
    canNext: ({ contribution: c }) => c.frequency === 'aucune' || c.amount > 0,
    render: ({ contribution: c, setContribution: set }) => (
      <div className="flex flex-col gap-8">
        <ChoicePills label="Fréquence des ajouts" options={FREQUENCIES} value={c.frequency} onChange={(frequency) => set({ frequency })} />
        {c.frequency !== 'aucune' && (
          <div className="fade-in flex flex-col gap-2">
            <span className="text-center text-lg font-semibold text-navy">Combien à chaque fois?</span>
            <AmountInput label="Montant par ajout" value={c.amount} onChange={(amount) => set({ amount })} presets={[50, 100, 250, 500, 1000]} />
          </div>
        )}
      </div>
    ),
  },
  {
    question: 'À quoi va servir cet argent?',
    hint: 'Choisis ce qui te correspond le mieux.',
    pose: 'map',
    pepite: 'Ton objectif, c’est notre boussole.',
    render: ({ profile: p, setProfile: set }) => (
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
    render: ({ profile: p, setProfile: set }) => <Slider label="Horizon" value={p.horizon} min={1} max={30} format={(v) => (v === 1 ? '1 an' : `${v} ans`)} onChange={(horizon) => set({ horizon })} />,
  },
  {
    question: 'Ton portefeuille perd 20 % en un mois. Que fais-tu?',
    hint: 'Il n’y a pas de mauvaise réponse.',
    pose: 'surprised',
    pepite: 'Sois honnête, ça reste entre nous!',
    render: ({ profile: p, setProfile: set }) => (
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
    render: ({ profile: p, setProfile: set }) => <Scale label="Aisance" value={p.comfort} minLabel="Pas du tout" maxLabel="Très à l’aise" onChange={(comfort) => set({ comfort })} />,
  },
]

export default function Profile() {
  const { step: raw } = useParams()
  const step = Number(raw)
  const navigate = useNavigate()
  const answers = useApp()
  if (!(step >= 1 && step <= STEPS.length)) return <Navigate to="/profil/1" replace />
  const s = STEPS[step - 1]
  return (
    <QuestionShell
      chapter="Ton profil"
      step={step}
      total={STEPS.length}
      question={s.question}
      hint={s.hint}
      pose={s.pose}
      pepite={typeof s.pepite === 'function' ? s.pepite(answers) : s.pepite}
      canNext={s.canNext?.(answers) ?? true}
      onBack={() => navigate(step === 1 ? '/' : `/profil/${step - 1}`)}
      onNext={() => navigate(step === STEPS.length ? '/transition' : `/profil/${step + 1}`)}
    >
      {s.render(answers)}
    </QuestionShell>
  )
}
