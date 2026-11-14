import { useCallback, useEffect, useRef, useState } from 'react'
import introUrl from '../../../assets/intro/intro.mp4'

const SEEN_KEY = 'bas-de-laine-intro'
const FADE_MS = 400
const MAX_MS = 6000 // filet si la vidéo ne démarre jamais

function shouldPlay() {
  if (!window.matchMedia('(prefers-reduced-motion: no-preference)').matches) return false
  try {
    return !sessionStorage.getItem(SEEN_KEY)
  } catch {
    return true
  }
}

/** Intro « BNCD | MonPort » jouée à l’ouverture de l’app, une fois par session. Un clic ou Échap la passe. */
export function Splash() {
  const [phase, setPhase] = useState<'playing' | 'leaving' | 'done'>(() => (shouldPlay() ? 'playing' : 'done'))
  const video = useRef<HTMLVideoElement>(null)
  const finish = useCallback(() => setPhase((p) => (p === 'playing' ? 'leaving' : p)), [])

  useEffect(() => {
    if (phase === 'playing') {
      video.current?.play().catch(finish)
      const timer = setTimeout(finish, MAX_MS)
      const onKey = (e: KeyboardEvent) => e.key === 'Escape' && finish()
      window.addEventListener('keydown', onKey)
      return () => {
        clearTimeout(timer)
        window.removeEventListener('keydown', onKey)
      }
    }
    if (phase === 'leaving') {
      try {
        sessionStorage.setItem(SEEN_KEY, '1')
      } catch {
        // stockage bloqué : l’intro rejouera au prochain chargement
      }
      const timer = setTimeout(() => setPhase('done'), FADE_MS)
      return () => clearTimeout(timer)
    }
  }, [phase, finish])

  if (phase === 'done') return null
  return (
    <button
      type="button"
      aria-label="Passer l’intro"
      onClick={finish}
      className={`fixed inset-0 z-50 cursor-default bg-white transition-opacity duration-[400ms] ${phase === 'leaving' ? 'opacity-0' : ''}`}
    >
      <video
        ref={video}
        src={introUrl}
        muted
        playsInline
        autoPlay
        preload="auto"
        aria-hidden
        onEnded={finish}
        onError={finish}
        className="h-full w-full object-contain"
      />
    </button>
  )
}
