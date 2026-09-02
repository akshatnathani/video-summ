import type { ReactNode } from 'react';

const INLINE_RE =
  /(\*\*[^*]+\*\*)|(`[^`]+`)|(\[([^\]]+)\]\(([^)\s]+)\))|(\*[^*]+\*)/g;

function renderInline(text: string, baseKey: number): ReactNode[] {
  const parts: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const key = `${baseKey}-${i++}`;
    if (m[1]) {
      parts.push(
        <strong key={key}>{renderInline(m[1].slice(2, -2), i)}</strong>,
      );
    } else if (m[2]) {
      parts.push(<code key={key}>{m[2].slice(1, -1)}</code>);
    } else if (m[3]) {
      parts.push(
        <a key={key} href={m[5]} target="_blank" rel="noopener noreferrer">
          {m[4]}
        </a>,
      );
    } else if (m[6]) {
      parts.push(<em key={key}>{m[6].slice(1, -1)}</em>);
    }
    last = INLINE_RE.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

const isListBullet = (l: string) => /^\s*[-*+]\s+/.test(l);
const isListOrdered = (l: string) => /^\s*\d+[.)]\s+/.test(l);
const isHeading = (l: string) => /^#{1,4}\s+/.test(l);
const isHr = (l: string) => /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(l);

/** Lightweight markdown → React. Enough for LLM summaries: headings, lists, emphasis. */
export default function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.split(/\r?\n/);
  const out: ReactNode[] = [];
  const key = () => out.length;

  for (let i = 0; i < lines.length; ) {
    const line = lines[i];

    if (isHr(line)) {
      out.push(<hr key={key()} className="rule my-4 border-t" />);
      i++;
      continue;
    }

    const head = /^(#{1,4})\s+(.*)$/.exec(line);
    if (head) {
      const level = head[1].length;
      const text_n = head[2];
      i++;
      if (level === 1) {
        out.push(<h1 key={key()}>{renderInline(text_n, key())}</h1>);
      } else if (level === 2) {
        out.push(<h2 key={key()}>{renderInline(text_n, key())}</h2>);
      } else {
        out.push(<h3 key={key()}>{renderInline(text_n, key())}</h3>);
      }
      continue;
    }

    if (isListBullet(line) || isListOrdered(line)) {
      const ordered = isListOrdered(line);
      const items: ReactNode[] = [];
      while (i < lines.length && (isListBullet(lines[i]) || isListOrdered(lines[i]))) {
        const item = (lines[i] || '').replace(/^\s*([-*+]|\d+[.)])\s+/, '');
        items.push(
          <li key={items.length}>{renderInline(item, key())}</li>,
        );
        i++;
      }
      out.push(ordered ? <ol key={key()}>{items}</ol> : <ul key={key()}>{items}</ul>);
      continue;
    }

    if (line.trim() === '') {
      i++;
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !isHeading(lines[i]) &&
      !isListBullet(lines[i]) &&
      !isListOrdered(lines[i]) &&
      !isHr(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    const joined = para.join('\n');
    const isQuote = joined.startsWith('>');
    const body = isQuote ? joined.replace(/^\s*>\s?/, '') : joined;
    const el = isQuote ? <blockquote key={key()}>{renderInline(body, key())}</blockquote>
      : <p key={key()} className="whitespace-pre-line">{renderInline(body, key())}</p>;
    out.push(el);
  }

  return <div className={className}>{out}</div>;
}