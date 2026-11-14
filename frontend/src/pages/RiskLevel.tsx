import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChoiceList } from '../components/inputs'
import { QuestionShell } from '../components/QuestionShell'
import { DEFAULT_PROFILE, useApp } from '../store'

const LEVELS = [
  { value: 25, label: 'Prudent', desc: 'Environ 30 % en actions. Des variations douces.' },
  { value: 50, label: 'Modéré', desc: 'Environ 50 % en actions. Un équilibre croissance et stabilité.' },
  { value: 80, label: 'Audacieux', desc: 'Environ 70 % en actions. Plus de hauts et de bas.' },
].map((l) => ({ ...l, desc: l.desc.replace(' %', ' %') }))

/** Raccourci : le niveau choisi remplace le profil (aisance 3 et 10 000 $ par défaut). */
export default function RiskLevel() {
  const navigate = useNavigate()
  const current = useApp((s) => s.riskOverride)
  const setRiskOverride = useApp((s) => s.setRiskOverride)
  const setProfile = useApp((s) => s.setProfile)
  const [value, setValue] = useState<number | undefined>(current ?? undefined)
  return (
    <QuestionShell
      chapter="Ton niveau de risque"
      step={1}
      total={1}
      question="Quel niveau de risque te convient?"
      hint="Tu pourras ajuster ensuite avec Pépite."
      pose="flag"
      pepite="Tu sais où tu vas : allons-y!"
      canNext={value != null}
      onBack={() => navigate('/')}
      onNext={() => {
        setProfile({ comfort: DEFAULT_PROFILE.comfort, amount: DEFAULT_PROFILE.amount })
        setRiskOverride(value!)
        navigate('/preferences/1')
      }}
    >
      <ChoiceList label="Niveau de risque" options={LEVELS} value={value} onChange={setValue} />
    </QuestionShell>
  )
}
