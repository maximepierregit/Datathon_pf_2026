import { Link } from 'react-router-dom'
import { Pepite } from '../components/Pepite'
import { Arrow, Badge, Separator } from '../components/ui'
import { useApp } from '../store'

const HOW = [
  { title: 'Parle-nous de toi', text: 'Ton profil, puis ce que tu veux (ou pas) dans ton portefeuille.' },
  { title: 'Trois agents s’y mettent', text: 'L’Éclaireur, le Compositeur et le Vérificateur construisent trois propositions.' },
  { title: 'Tu choisis', text: 'Compare, ajuste avec Pépite, garde ce qui te ressemble.' },
]

export default function Home() {
  const reset = useApp((s) => s.reset)
  return (
    <>
      <section className="bg-white">
        <div className="mx-auto flex max-w-[1020px] flex-col items-center gap-8 px-4 py-14 text-center sm:px-6 md:flex-row md:py-20 md:text-left">
          <div className="flex flex-1 flex-col items-center gap-2 md:items-start">
            <span className="text-sm font-semibold text-red">Salut, moi c’est Pépite</span>
            <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[54px]">Construisons un portefeuille qui te ressemble.</h1>
            <Separator />
            <p className="m-0 max-w-[560px] text-lg text-ink-soft">
              Quelques questions, trois agents IA, et trois propositions de portefeuille. Tu gardes toujours le dernier mot.
            </p>
          </div>
          <Pepite pose="wave" size={240} className="bob shrink-0" alt="Pépite, une petite montagne enneigée avec une écharpe rouge, te fait coucou" />
        </div>
      </section>

      <section className="bg-mist">
        <div className="mx-auto grid max-w-[1020px] gap-4 px-4 py-12 sm:px-6 md:grid-cols-2">
          <Link
            to="/profil/1"
            onClick={reset}
            className="on-dark group flex flex-col gap-3 rounded-[var(--radius-card)] bg-navy p-7 text-white no-underline transition-shadow hover:shadow-[var(--shadow-hover)]"
          >
            <span className="flex items-center justify-between">
              <span className="text-[24px] font-semibold leading-7">Répondre à quelques questions</span>
              <Badge tone="red">Recommandé</Badge>
            </span>
            <span className="text-white/80">6 questions sur toi, puis tes préférences. Environ 3 minutes.</span>
            <span className="mt-auto inline-flex items-center gap-2 pt-2 font-medium">
              Commencer <Arrow />
            </span>
          </Link>
          <Link
            to="/niveau"
            onClick={reset}
            className="group flex flex-col gap-3 rounded-[var(--radius-card)] border border-line-soft bg-white p-7 text-ink no-underline transition-shadow hover:shadow-[var(--shadow-hover)]"
          >
            <span className="text-[24px] font-semibold leading-7 text-navy">Choisir mon niveau de risque</span>
            <span className="text-ink-soft">Tu sais déjà ce que tu veux? Choisis parmi 3 niveaux : prudent, modéré ou audacieux.</span>
            <span className="mt-auto inline-flex items-center gap-2 pt-2 font-medium text-red">
              Choisir un niveau <Arrow />
            </span>
          </Link>
        </div>
      </section>

      <section className="bg-white">
        <div className="mx-auto max-w-[1020px] px-4 py-12 sm:px-6">
          <h2 className="text-[30px] font-light leading-9 text-slate">Comment ça marche</h2>
          <Separator />
          <ol className="m-0 grid list-none gap-6 p-0 md:grid-cols-3">
            {HOW.map((h, i) => (
              <li key={h.title} className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky text-sm font-semibold text-navy">{i + 1}</span>
                <span className="flex flex-col">
                  <span className="font-semibold text-navy">{h.title}</span>
                  <span className="text-[15px] text-ink-soft">{h.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  )
}
