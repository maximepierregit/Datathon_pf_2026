const files = import.meta.glob('../../../assets/mascot/svg/*.svg', { eager: true, query: '?url', import: 'default' }) as Record<
  string,
  string
>

export type Pose =
  | 'wave' | 'happy' | 'question' | 'thinking' | 'surprised' | 'coffee' | 'laptop' | 'map'
  | 'binoculars' | 'thumbsup' | 'sleep' | 'tired' | 'cool' | 'excited' | 'flag'

const POSES = Object.fromEntries(
  Object.entries(files).map(([path, url]) => [path.split('/').pop()!.replace(/^\d+-|\.svg$/g, ''), url]),
) as Record<Pose, string>

export function Pepite({ pose, size = 120, alt = '', className = '' }: { pose: Pose; size?: number; alt?: string; className?: string }) {
  return <img src={POSES[pose]} width={size} height={size} alt={alt} aria-hidden={alt ? undefined : true} className={className} />
}

/** Pépite qui parle : la mascotte avec une bulle. */
export function PepiteSays({ pose, children, size = 96 }: { pose: Pose; children: React.ReactNode; size?: number }) {
  return (
    <div className="flex items-end gap-3">
      <Pepite pose={pose} size={size} className="shrink-0" />
      <div className="relative mb-4 rounded-[var(--radius-card)] bg-sky px-4 py-3 text-[15px] leading-6 text-navy">
        <span className="absolute -left-1.5 bottom-3 h-3 w-3 rotate-45 bg-sky" aria-hidden />
        {children}
      </div>
    </div>
  )
}
