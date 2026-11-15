import { useNavigate } from 'react-router-dom'
import { Pepite } from '../components/Pepite'
import { Arrow, Button, Separator } from '../components/ui'
import { riskLabel, riskScore } from '../lib/engine'
import { contribution, money } from '../lib/format'
import { useApp } from '../store'

const OBJECTIVE = { securiser: 'Sécuriser', fructifier: 'Faire fructifier', 'viser-haut': 'Viser haut' }

/** Entre le profil et les préférences : récapitulatif, puis on précise ou on passe. */
export default function Transition() {
  const navigate = useNavigate()
  const state = useApp()
  const { profile } = state
  const facts: [string, string][] = [
    ['Âge', `${profile.age} ans`],
    ['Montant', money(profile.amount)],
    ['Ajouts', contribution(state.contribution)],
    ['Objectif', OBJECTIVE[profile.objective]],
    ['Horizon', `${profile.horizon} ans`],
    ['Aisance', `${profile.comfort} / 5`],
  ]

  return (
    <div className="flex flex-1 flex-col">
      <div className="h-1 bg-red" aria-hidden />
      <div className="fade-in mx-auto flex w-full max-w-[640px] flex-1 flex-col items-center gap-6 px-4 py-12 text-center sm:px-6 md:py-16">
        <Pepite pose="thumbsup" size={150} className="bob" />
        <div className="flex flex-col items-center">
          <span className="text-sm font-semibold text-slate">Étape 1 terminée</span>
          <h1 className="text-[30px] font-semibold leading-9 text-navy md:text-[38px] md:leading-[44px]">Ton profil est {riskLabel(riskScore(profile, state.contribution)).toLowerCase()}.</h1>
          <Separator />
        </div>
        <dl className="m-0 grid w-full grid-cols-2 gap-2 sm:grid-cols-3">
          {facts.map(([k, v]) => (
            <div key={k} className="rounded-[var(--radius-card)] border border-line-soft px-4 py-2">
              <dt className="text-xs text-ink-soft">{k}</dt>
              <dd className="m-0 font-semibold text-navy">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-col gap-2 rounded-[var(--radius-card)] bg-sky px-6 py-5">
          <p className="m-0 font-semibold text-navy">Veux-tu préciser ce que tu veux dans ton portefeuille?</p>
          <p className="m-0 text-[15px] text-ink-soft">
            FNB ou non, types de placements, régions, thématiques{profile.comfort >= 4 ? ', styles d’investissement' : ''} : environ 2 minutes. Sinon, mes agents choisissent pour toi.
          </p>
        </div>
        <div className="flex w-full flex-col-reverse items-center justify-center gap-3 sm:flex-row">
          <Button
            variant="tertiary"
            onClick={() => {
              state.clearConstraints()
              navigate('/verification')
            }}
          >
            Passer cette étape
          </Button>
          <Button onClick={() => navigate('/preferences/1')}>
            Préciser mes préférences <Arrow />
          </Button>
        </div>
        <Button variant="ghost" onClick={() => navigate('/profil/7')}>
          <Arrow back /> Modifier mon profil
        </Button>
      </div>
    </div>
  )
}
