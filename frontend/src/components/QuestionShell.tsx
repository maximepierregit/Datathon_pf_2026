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

/** Une question par écran : grande question, composant de réponse, Retour / Continuer. */
export function QuestionShell({ chapter, step, total, question, hint, pose, pepite, canNext, nextLabel = 'Continuer', onBack, onNext, children, aside }: Props) {
  return (
    <div className="flex flex-1 flex-col">
      <div className="h-1 bg-mist" aria-hidden>
        <div className="h-full bg-red transition-[width] duration-300" style={{ width: `${(step / total) * 100}%` }} />
      </div>
      <div className="mx-auto grid w-full max-w-[1020px] flex-1 gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1fr_200px] md:py-16">
        <div key={question} className="fade-in flex max-w-[640px] flex-col gap-8">
          <div className="flex flex-col gap-3">
            <span className="text-sm font-semibold text-slate">
              {chapter} · {step} / {total}
            </span>
            <h1 className="text-[30px] font-semibold leading-9 text-navy md:text-[38px] md:leading-[44px]">{question}</h1>
            {hint && <p className="m-0 text-ink-soft">{hint}</p>}
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
        <div className="hidden flex-col items-center gap-3 self-center md:flex">
          {pepite && <p className="m-0 rounded-[var(--radius-card)] bg-sky px-4 py-3 text-center text-sm text-navy">{pepite}</p>}
          <Pepite pose={pose} size={180} className="bob" />
        </div>
      </div>
    </div>
  )
}
