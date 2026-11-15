import { useEffect, useState } from 'react'
import { DEMO_EVENT, isDemo } from '../api'

/** Bandeau visible quand les agents n'ont pas répondu : les résultats affichés viennent alors du moteur d'exemple. */
export function DemoBanner() {
  const [demo, setDemo] = useState(isDemo)
  useEffect(() => {
    const on = (e: Event) => setDemo(Boolean((e as CustomEvent<boolean>).detail))
    window.addEventListener(DEMO_EVENT, on)
    return () => window.removeEventListener(DEMO_EVENT, on)
  }, [])
  if (!demo) return null
  return (
    <div role="status" className="bg-[#FDECEC] px-4 py-2 text-center text-sm text-red-dark">
      <strong className="font-semibold">Mode démonstration : </strong>
      mes agents ne répondent pas pour l’instant. Les résultats affichés sont des exemples.
    </div>
  )
}
