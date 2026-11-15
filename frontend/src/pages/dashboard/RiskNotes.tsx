import { useState } from 'react'
import { Pepite } from '../../components/Pepite'
import type { Portfolio, RiskNote } from '../../types'

/** Les mises en garde du responsable des risques : colonne de gauche sur grand écran, au-dessus du portefeuille sinon. */
export function RiskNotes({ p }: { p: Portfolio }) {
  const notes = p.warnings
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
            <Note key={n.title} note={n} />
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

function Note({ note }: { note: RiskNote }) {
  const [open, setOpen] = useState(false)
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
    </li>
  )
}
