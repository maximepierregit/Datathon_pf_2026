import { Pepite, type Pose } from './Pepite'
import { Arrow, Button } from './ui'

interface Props {
  chapter: string
  step: number
  total: number
  question: string
  hint?: string
  pose: Pose
  pepite?: string
  canNext: boolean
  nextLabel?: string
  onBack: () => void
  onNext: () => void
  children: React.ReactNode
  aside?: React.ReactNode
}

/**
 * Une question par écran, en colonne centrée.
 * Pépite parle au-dessus de la question : on la lit d'abord, puis on répond, sans quitter l'axe central.
 */
export function QuestionShell({ chapter, step, total, question, hint, pose, pepite, canNext, nextLabel = 'Continuer', onBack, onNext, children, aside }: Props) {
  return (
    <div className="flex flex-1 flex-col">
      <div className="h-1 bg-mist" aria-hidden>
        <div className="h-full bg-red transition-[width] duration-300" style={{ width: `${(step / total) * 100}%` }} />
      </div>
      <div key={question} className="fade-in mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-10 px-4 py-10 sm:px-6 md:py-14">
        <div className="flex flex-col items-center gap-6 text-center">
          <div className="flex items-center gap-4">
            <Pepite pose={pose} size={140} className="bob shrink-0 max-sm:h-24 max-sm:w-24" />
            {pepite && (
              <p className="relative m-0 max-w-[320px] rounded-[var(--radius-card)] bg-sky px-5 py-3 text-left text-base leading-6 text-navy">
                <span className="absolute -left-1.5 top-1/2 h-3 w-3 -translate-y-1/2 rotate-45 bg-sky" aria-hidden />
                {pepite}
              </p>
            )}
          </div>
          <div className="flex flex-col items-center gap-3">
            <span className="text-base font-semibold text-slate">
              {chapter} · {step} / {total}
            </span>
            <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[56px]">{question}</h1>
            {hint && <p className="m-0 max-w-[600px] text-lg text-ink-soft">{hint}</p>}
          </div>
        </div>
        {children}
        {aside}
        <div className="flex items-center justify-between gap-3 pt-2">
          <Button variant="ghost" onClick={onBack}>
            <Arrow back /> Retour
          </Button>
          <Button onClick={onNext} disabled={!canNext}>
            {nextLabel} <Arrow />
          </Button>
        </div>
      </div>
    </div>
  )
}
