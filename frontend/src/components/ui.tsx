import { Link, type LinkProps } from 'react-router-dom'

type Variant = 'primary' | 'secondary' | 'tertiary' | 'ghost'

const base =
  'inline-flex min-h-11 min-w-32 items-center justify-center gap-2 rounded-[var(--radius-pill)] border px-6 py-2.5 text-base font-medium leading-[18px] tracking-[0.5px] transition-colors hover:shadow-[var(--shadow-hover)] disabled:opacity-40 disabled:hover:shadow-none'

const variants: Record<Variant, string> = {
  primary: 'border-red bg-red text-white hover:border-red-hover hover:bg-red-hover active:bg-[#BE171D]',
  secondary: 'border-red bg-transparent text-red hover:bg-red hover:text-white',
  tertiary: 'border-slate bg-transparent text-slate hover:bg-slate hover:text-white',
  ghost: 'min-w-0 border-transparent px-2 text-slate hover:shadow-none hover:text-navy',
}

export function Button({ variant = 'primary', className = '', ...rest }: React.ComponentProps<'button'> & { variant?: Variant }) {
  return <button type="button" className={`${base} ${variants[variant]} ${className}`} {...rest} />
}

export function ButtonLink({ variant = 'primary', className = '', ...rest }: LinkProps & { variant?: Variant }) {
  return <Link className={`${base} ${variants[variant]} ${className}`} {...rest} />
}

/** Signature BNC : petit séparateur rouge sous les titres. */
export function Separator() {
  return <span className="my-[15px] block h-[2px] w-[30px] bg-red" aria-hidden />
}

export function Card({ className = '', ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-[var(--radius-card)] border border-line-soft bg-white p-6 ${className}`} {...rest} />
}

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <span className="text-sm font-semibold tracking-[0.3px] text-red">{children}</span>
}

export function Arrow({ back = false }: { back?: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={back ? 'M19 12H5M11 6l-6 6 6 6' : 'M5 12h14M13 6l6 6-6 6'} />
    </svg>
  )
}

export function Badge({ children, tone = 'sky' }: { children: React.ReactNode; tone?: 'sky' | 'red' | 'mist' }) {
  const tones = { sky: 'bg-sky text-navy', red: 'bg-red text-white', mist: 'bg-mist text-slate' }
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${tones[tone]}`}>{children}</span>
}

export function Alert({ children, title = 'Attention' }: { children: React.ReactNode; title?: string }) {
  return (
    <div role="status" className="flex gap-3 rounded-[var(--radius-card)] border-l-0 bg-[#FDECEC] px-4 py-3 text-[15px] text-red-dark">
      <svg className="mt-0.5 shrink-0" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
        <path d="M12 3l10 18H2zM12 10v5M12 18h.01" />
      </svg>
      <div>
        <strong className="font-semibold">{title} : </strong>
        {children}
      </div>
    </div>
  )
}
