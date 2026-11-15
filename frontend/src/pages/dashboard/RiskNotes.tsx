import { useMemo, useState } from 'react'
import { Pepite } from '../../components/Pepite'
import { evidenceOf } from '../../lib/engine'
import { useApp } from '../../store'
import type { Evidence, Portfolio, RiskNote } from '../../types'
import { EvidenceCard } from './Evidence'

/** Les mises en garde du responsable des risques : colonne de gauche sur grand écran, au-dessus du portefeuille sinon. */
export function RiskNotes({ p }: { p: Portfolio }) {
  const notes = p.warnings
  const profile = useApp((s) => s.profile)
  // Moteur d'exemple : les preuves citées sont calculées ici, sur le portefeuille affiché.
  const example = useMemo(() => (notes.some((n) => !n.sources && n.cites) ? evidenceOf(p, profile) : {}), [notes, p, profile])
  return (
    <section aria-label="Le responsable des risques" className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <Pepite pose="flag" size={40} className="shrink-0" />
        <div className="flex flex-col">
          <span className="text-[15px] font-semibold leading-5 text-navy">Le responsable des risques</span>
          <span className="text-[13px] text-ink-soft">{notes.length ? `${notes.length} point${notes.length > 1 ? 's' : ''} à lire avant de choisir` : 'A relu ce portefeuille'}</span>
        </div>
      </div>
      {notes.length ? (
        <ul className="m-0 grid list-none gap-2.5 p-0 sm:grid-cols-2 xl:grid-cols-1">
          {notes.map((n) => (
            <Note key={n.title} note={n} sources={n.sources ?? (n.cites ?? []).map((id) => example[id]).filter(Boolean)} />
          ))}
        </ul>
      ) : (
        <div className="flex items-start gap-2.5 rounded-[var(--radius-card)] border border-line-soft bg-white px-3.5 py-3 text-sm text-ink-soft">
          <svg className="mt-0.5 shrink-0 text-navy" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M5 12l5 5L20 7" />
          </svg>
          Rien de particulier à signaler pour ce portefeuille.
        </div>
      )}
    </section>
  )
}

const LONG = 140

function Note({ note, sources }: { note: RiskNote; sources: Evidence[] }) {
  const [open, setOpen] = useState(false)
  const [proofs, setProofs] = useState(false)
  const high = note.severity === 'high'
  const long = note.detail.length > LONG
  return (
    <li className="flex flex-col gap-1.5 rounded-[var(--radius-card)] border border-line-soft bg-white px-3.5 py-3">
      <span className={`flex items-center gap-1.5 text-xs font-semibold ${high ? 'text-red-dark' : 'text-taupe'}`}>
        <span className={`h-2 w-2 rounded-full ${high ? 'bg-red' : 'bg-taupe'}`} aria-hidden />
        {high ? 'Important' : 'À savoir'}
      </span>
      <span className="text-[15px] font-semibold leading-5 text-navy">{note.title}</span>
      {note.detail && (
        <p className={`m-0 text-sm leading-[21px] text-ink-soft ${long && !open ? 'line-clamp-3' : ''}`}>{note.detail}</p>
      )}
      {long && (
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="self-start text-[13px] font-medium text-blue hover:text-blue-dark">
          {open ? 'Réduire' : 'Lire la suite'}
        </button>
      )}
      {sources.length > 0 && (
        <>
          <button
            onClick={() => setProofs((o) => !o)}
            aria-expanded={proofs}
            className="group -ml-1 flex items-center gap-1.5 self-start rounded-full py-0.5 pl-1 pr-2.5 text-[13px] font-medium text-blue hover:bg-sky hover:text-blue-dark"
          >
            <Pepite pose="binoculars" size={24} className={`transition-transform motion-safe:group-hover:-rotate-6 ${proofs ? '-rotate-6' : ''}`} />
            {proofs ? 'Cacher les preuves' : `Voir les preuves (${sources.length})`}
          </button>
          {proofs && (
            <div className="fade-in flex flex-col gap-2">
              <p className="m-0 text-xs italic leading-4 text-ink-soft">Ces chiffres viennent des données, calculés par le code. Aucun n’est écrit par un agent.</p>
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {sources.map((e) => (
                  <EvidenceCard key={e.id} e={e} />
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </li>
  )
}
