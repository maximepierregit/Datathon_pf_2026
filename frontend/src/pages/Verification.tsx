import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { checkProfile } from '../api'
import { PepiteSays } from '../components/Pepite'
import { Arrow, Button, Card, Separator } from '../components/ui'
import { riskScore } from '../lib/engine'
import { useApp } from '../store'

/**
 * Pépite relit le questionnaire avant tout envoi aux gestionnaires.
 * Incohérent : elle montre les enjeux et propose de recommencer (ou de continuer avec 3 propositions).
 * Cohérent : une boîte de texte permet d'ajuster avant l'envoi.
 */
export default function Verification() {
  const navigate = useNavigate()
  const profile = useApp((s) => s.profile)
  const constraints = useApp((s) => s.constraints)
  const check = useApp((s) => s.check)
  const setCheck = useApp((s) => s.setCheck)
  const setSession = useApp((s) => s.setSession)
  const setAdjustment = useApp((s) => s.setAdjustment)
  const [draft, setDraft] = useState(useApp.getState().adjustment)
  const [answers, setAnswers] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ctrl = new AbortController()
    setCheck(null)
    setSession(null)
    checkProfile({ score: riskScore(profile), profile, constraints }, ctrl.signal)
      .then(({ check: c, session }) => {
        setCheck(c)
        setSession(session)
        setLoading(false)
      })
      .catch(() => {})
    return () => ctrl.abort()
    // La vérification ne se lance qu'une fois par visite.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const questions = check?.questions ?? []
  const send = () => {
    // Profil incohérent : les réponses aux questions de Pépite lui reviennent, elle s'y ajuste à la construction.
    if (check?.coherent) setAdjustment(draft.trim())
    else setAdjustment(answers.trim() ? `Mes réponses à tes questions :\n${questions.map((q) => `- ${q}`).join('\n')}\n${answers.trim()}` : '')
    navigate('/construction')
  }

  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-col gap-8 px-4 py-12 sm:px-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold text-slate">Avant d’envoyer tes consignes</span>
        <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[54px]">
          {loading || !check ? 'Pépite relit tes réponses' : check.coherent ? 'Tes réponses se tiennent' : 'Quelques réponses se contredisent'}
        </h1>
        <Separator />
      </div>

      {loading || !check ? (
        <PepiteSays pose="thinking">
          <span aria-live="polite">Je vérifie que ton profil et tes préférences vont dans le même sens…</span>
        </PepiteSays>
      ) : check.coherent ? (
        <>
          <PepiteSays pose="thumbsup">{check.summary}</PepiteSays>
          <div className="flex flex-col gap-2">
            <label htmlFor="adjustment" className="font-semibold text-navy">
              Un ajustement avant que j’envoie tes consignes aux gestionnaires? <span className="font-normal text-ink-soft">(facultatif)</span>
            </label>
            <textarea
              id="adjustment"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="Ex. : un peu plus de Canada, pas de banques…"
              className="rounded-[var(--radius-card)] border border-line bg-white px-3 py-2 text-[15px] outline-none focus:border-navy"
            />
            <p className="m-0 text-sm text-ink-soft">
              Trois gestionnaires vont se faire concurrence avec tes consignes. Le juge gardera le meilleur portefeuille pour toi.
            </p>
          </div>
          <div className="flex flex-col-reverse items-center justify-between gap-3 sm:flex-row">
            <Button variant="ghost" onClick={() => navigate('/preferences/1')}>
              <Arrow back /> Modifier mes préférences
            </Button>
            <Button onClick={send}>
              Envoyer aux gestionnaires <Arrow />
            </Button>
          </div>
        </>
      ) : (
        <>
          <PepiteSays pose="question">{check.summary}</PepiteSays>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {check.issues.map((issue) => (
              <li key={issue.title + issue.detail}>
                <Card className="flex flex-col gap-1 border-l-[3px] border-l-red">
                  <span className="font-semibold text-navy">{issue.title}</span>
                  <span className="text-[15px] text-ink">{issue.detail}</span>
                </Card>
              </li>
            ))}
          </ul>
          {questions.length > 0 && (
            <div className="flex flex-col gap-2">
              <PepiteSays pose="question">
                <span className="flex flex-col gap-1">
                  <span>Aide-moi à comprendre ce que tu veux vraiment :</span>
                  {questions.map((q) => (
                    <span key={q}>• {q}</span>
                  ))}
                </span>
              </PepiteSays>
              <label htmlFor="answers" className="font-semibold text-navy">
                Tes réponses <span className="font-normal text-ink-soft">(facultatif : je m’ajusterai en construisant tes portefeuilles)</span>
              </label>
              <textarea
                id="answers"
                value={answers}
                onChange={(e) => setAnswers(e.target.value)}
                maxLength={900}
                rows={3}
                placeholder="Ex. : la crypto, c’est un petit pari que j’assume…"
                className="rounded-[var(--radius-card)] border border-line bg-white px-3 py-2 text-[15px] outline-none focus:border-navy"
              />
            </div>
          )}
          <div className="flex flex-col gap-2 rounded-[var(--radius-card)] bg-sky px-6 py-5">
            <p className="m-0 font-semibold text-navy">Je te propose de recommencer le questionnaire.</p>
            <p className="m-0 text-[15px] text-ink-soft">
              Tes réponses restent remplies : tu n’as qu’à corriger ce qui cloche. Si tu préfères continuer, je te prépare trois portefeuilles : tes contraintes telles quelles,
              un 80/20 qui privilégie ton profil et un 80/20 qui privilégie tes préférences.
            </p>
          </div>
          <div className="flex flex-col-reverse items-center justify-between gap-3 sm:flex-row">
            <Button variant="tertiary" onClick={send}>
              Continuer avec 3 propositions
            </Button>
            <Button onClick={() => navigate('/profil/1')}>
              <Arrow back /> Recommencer le questionnaire
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
