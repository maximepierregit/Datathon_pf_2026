import { useEffect, useRef } from 'react'
import { Pepite } from '../../components/Pepite'
import { Button, Separator } from '../../components/ui'

const POINTS = [
  'MonPort propose des portefeuilles modèles à titre éducatif. Ce ne sont pas des recommandations personnalisées.',
  'Aucun ordre n’est passé : c’est toi qui décides si, quand et comment investir.',
  'Les rendements affichés sont des estimations, sans aucune garantie. Tu peux perdre de l’argent.',
]

/** Affiché une fois par session, à l'arrivée sur les portefeuilles. */
export function Disclaimer({ onAccept }: { onAccept: () => void }) {
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    button.current?.focus()
  }, [])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 px-4">
      <div role="alertdialog" aria-modal="true" aria-labelledby="disclaimer-title" aria-describedby="disclaimer-body" className="fade-in flex w-full max-w-[520px] flex-col items-center gap-2 rounded-[var(--radius-card)] bg-white px-6 py-8 text-center sm:px-10">
        <Pepite pose="question" size={96} />
        <h2 id="disclaimer-title" className="text-[24px] font-semibold leading-7 text-navy">
          Pépite n’est pas un conseiller financier
        </h2>
        <Separator />
        <ul id="disclaimer-body" className="m-0 flex list-none flex-col gap-3 p-0 text-left text-[15px]">
          {POINTS.map((p) => (
            <li key={p} className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-red" aria-hidden />
              {p}
            </li>
          ))}
        </ul>
        <p className="m-0 mt-2 text-sm text-ink-soft">Pour un conseil adapté à ta situation, parle à un conseiller autorisé.</p>
        <Button ref={button} className="mt-4" onClick={onAccept}>
          J’ai compris, voir mes portefeuilles
        </Button>
      </div>
    </div>
  )
}
