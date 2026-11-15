import { Fragment, useMemo, type ReactNode } from 'react'
import { pct } from '../lib/format'

/**
 * Les réponses de Pépite, en HTML simple (consigne dans backend/src/invest_agents/workflow/pepite.py).
 * Rien n'est injecté tel quel : on relit l'arbre et on ne garde que les balises connues, sans leurs attributs.
 * p, strong, em, ul, ol, li, h4, br, plus des balises maison : chiffre, barre, astuce, attention.
 * Un texte sans balise (ancien backend, réponses d'exemple) passe par un mini-Markdown.
 */
export function RichText({ text }: { text: string }) {
  const nodes = useMemo(() => {
    const html = /<\/?(p|ul|ol|li|strong|em|h4|br|chiffre|barre|astuce|attention)\b/i.test(text) ? text : fromPlain(text)
    const body = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body
    // <barre … /> n'est pas fermée en HTML : ce qui la suit s'y retrouve. On le remet à la suite.
    body.querySelectorAll('barre').forEach((b) => b.after(...b.childNodes))
    return children(body)
  }, [text])
  return <div className="flex flex-col gap-2.5 text-[15px] leading-6">{nodes}</div>
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Lignes « - » regroupées en liste, ligne courte sans ponctuation avant une liste = petit titre, **gras**. */
function fromPlain(text: string): string {
  const lines = text.trim().split('\n').map((l) => esc(l.trim()).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'))
  const bullet = (l: string) => /^[-•*]\s/.test(l)
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    if (!l) continue
    if (bullet(l)) {
      const items: string[] = []
      while (i < lines.length && bullet(lines[i])) items.push(`<li>${lines[i++].slice(2)}</li>`)
      i--
      out.push(`<ul>${items.join('')}</ul>`)
    } else if (l.length < 60 && !/[.!?:;,]$/.test(l) && bullet(lines[i + 1] ?? '')) out.push(`<h4>${l.replace(/^#+\s*/, '')}</h4>`)
    else out.push(`<p>${l.replace(/^#+\s*/, '')}</p>`)
  }
  return out.join('')
}

const DROP = new Set(['script', 'style', 'iframe', 'object', 'embed', 'img', 'svg', 'math', 'form', 'input', 'button', 'textarea', 'select', 'link', 'meta'])

const tag = (n: Node) => (n.nodeType === Node.ELEMENT_NODE ? (n as Element).tagName.toLowerCase() : '')
const blank = (n: Node) => n.nodeType === Node.TEXT_NODE && !n.textContent?.trim()

/** Les chiffres et les barres qui se suivent forment un seul bloc (grille de chiffres, pile de barres). */
function children(parent: Node): ReactNode[] {
  const out: ReactNode[] = []
  const list = [...parent.childNodes]
  for (let i = 0; i < list.length; i++) {
    const kind = tag(list[i])
    if (kind === 'chiffre' || kind === 'barre') {
      const run: Element[] = []
      let j = i
      while (j < list.length && (tag(list[j]) === kind || blank(list[j]))) {
        if (tag(list[j]) === kind) run.push(list[j] as Element)
        j++
      }
      out.push(kind === 'chiffre' ? <Figures key={i} items={run} /> : <Bars key={i} items={run} />)
      i = j - 1
      continue
    }
    out.push(node(list[i], i))
  }
  return out
}

function node(n: Node, key: number): ReactNode {
  if (n.nodeType === Node.TEXT_NODE) return n.textContent
  if (n.nodeType !== Node.ELEMENT_NODE) return null
  const kind = tag(n)
  if (DROP.has(kind)) return null
  const inner = children(n)
  switch (kind) {
    case 'p':
      return <p key={key} className="m-0">{inner}</p>
    case 'strong':
    case 'b':
      return <strong key={key} className="font-semibold">{inner}</strong>
    case 'em':
    case 'i':
      return <em key={key}>{inner}</em>
    case 'br':
      return <br key={key} />
    case 'h3':
    case 'h4':
    case 'h5':
      return <p key={key} className="m-0 text-[13px] font-semibold uppercase tracking-[0.4px] text-slate">{inner}</p>
    case 'ul':
      return (
        <ul key={key} className="m-0 flex list-none flex-col gap-1.5 p-0">
          {[...n.childNodes].filter((c) => tag(c) === 'li').map((li, k) => (
            <li key={k} className="flex gap-2.5">
              <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-red" aria-hidden />
              <span>{children(li)}</span>
            </li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol key={key} className="m-0 flex list-none flex-col gap-2 p-0">
          {[...n.childNodes].filter((c) => tag(c) === 'li').map((li, k) => (
            <li key={k} className="flex gap-2.5">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-navy text-[11px] font-semibold text-white">{k + 1}</span>
              <span>{children(li)}</span>
            </li>
          ))}
        </ol>
      )
    case 'astuce':
      return (
        <div key={key} className="flex gap-2.5 rounded-[var(--radius-card)] bg-white px-3 py-2.5">
          <svg className="mt-0.5 shrink-0 text-blue" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z" />
          </svg>
          <div className="flex flex-col gap-1.5">{inner}</div>
        </div>
      )
    case 'attention':
      return (
        <div key={key} className="flex gap-2.5 rounded-[var(--radius-card)] bg-[#FDECEC] px-3 py-2.5 text-red-dark">
          <svg className="mt-0.5 shrink-0" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
            <path d="M12 3l10 18H2zM12 10v5M12 18h.01" />
          </svg>
          <div className="flex flex-col gap-1.5">{inner}</div>
        </div>
      )
    default:
      return <Fragment key={key}>{inner}</Fragment>
  }
}

function Figures({ items }: { items: Element[] }) {
  return (
    <div className={`grid gap-2 ${items.length > 1 ? 'grid-cols-2' : ''}`}>
      {items.map((el, k) => (
        <div key={k} className="flex flex-col rounded-[var(--radius-card)] bg-white px-3 py-2">
          <span className="text-[22px] font-semibold leading-7 text-navy">{el.getAttribute('valeur')}</span>
          <span className="text-[13px] leading-5 text-ink-soft">{el.textContent}</span>
        </div>
      ))}
    </div>
  )
}

function Bars({ items }: { items: Element[] }) {
  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-card)] bg-white px-3 py-2.5">
      {items.map((el, k) => {
        const raw = parseFloat((el.getAttribute('pct') ?? '').replace(',', '.'))
        const v = Number.isFinite(raw) ? Math.min(100, Math.max(0, raw)) : 0
        return (
          <div key={k} className="flex flex-col gap-1">
            <span className="flex justify-between text-[13px]">
              <span className="text-ink">{el.getAttribute('nom')}</span>
              <span className="font-semibold text-navy">{pct(v / 100, 0)}</span>
            </span>
            <span className="h-1.5 overflow-hidden rounded-full bg-mist" aria-hidden>
              <span className="block h-full rounded-full bg-navy" style={{ width: `${v}%` }} />
            </span>
          </div>
        )
      })}
    </div>
  )
}
