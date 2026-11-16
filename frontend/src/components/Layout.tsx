import { useEffect } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { DemoBanner } from './DemoBanner'
import { Pepite } from './Pepite'

const STEPS = [
  { label: 'Ton profil', match: ['/profil', '/transition'] },
  { label: 'Tes préférences', match: ['/preferences'] },
  { label: 'Vérification', match: ['/verification'] },
  { label: 'Construction', match: ['/construction'] },
  { label: 'Portefeuilles', match: ['/portefeuille'] },
]

function Header() {
  const { pathname } = useLocation()
  const current = STEPS.findIndex((s) => s.match.some((m) => pathname.startsWith(m)))
  return (
    // Sur le tableau de bord, l'en-tête reste en haut : le chat de Pépite se cale juste dessous.
    <header className={`on-dark bg-navy text-white ${pathname.startsWith('/portefeuille') ? 'sticky top-0 z-30' : ''}`}>
      <div className="mx-auto flex max-w-[1020px] flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link to="/" className="flex items-center gap-2 text-lg font-semibold text-white no-underline">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white">
            <Pepite pose="happy" size={34} />
          </span>
          MonPort
        </Link>
        {current >= 0 && (
          <ol aria-label="Progression" className="m-0 flex list-none flex-wrap items-center gap-x-5 gap-y-1 p-0 text-sm font-medium">
            {STEPS.map((s, i) => (
              <li key={s.label} aria-current={i === current ? 'step' : undefined} className={`flex items-center gap-2 ${i <= current ? 'text-white' : 'text-slate-light'}`}>
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${i < current ? 'bg-white text-navy' : i === current ? 'bg-red text-white' : 'border border-slate-light'}`}>
                  {i < current ? '✓' : i + 1}
                </span>
                <span className="hidden sm:inline">{s.label}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="border-t border-line-soft bg-mist px-4 py-5 text-center text-xs leading-5 text-ink-soft">
      Prototype réalisé pour le Datathon 2026 · MonPort propose des portefeuilles modèles à titre éducatif.
      <br />
      Ceci n’est pas un conseil financier : c’est toi qui décides.
    </footer>
  )
}

export function Layout() {
  const { pathname } = useLocation()
  // Chaque écran a son URL : on l'ouvre en haut de page.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <DemoBanner />
      <main className="flex flex-1 flex-col">
        <Outlet />
      </main>
      <Footer />
    </div>
  )
}
