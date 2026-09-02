import { useEffect, useState, type ReactNode } from 'react';
import { cn } from '../lib';

export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn('label', className)}>{children}</p>;
}

export function Box({
  children,
  strong,
  hover,
  className,
  as: As = 'div',
  ...rest
}: {
  children: ReactNode;
  strong?: boolean;
  hover?: boolean;
  className?: string;
  as?: 'div' | 'section' | 'article' | 'li';
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <As className={cn(strong ? 'box-strong' : 'box', hover && 'box-hover', className)} {...rest}>
      {children}
    </As>
  );
}

export function Rule({ className }: { className?: string }) {
  return <hr className={cn('rule border-t', className)} />;
}

export function SectionHead({
  title,
  meta,
  note,
}: {
  title: string;
  meta?: ReactNode;
  note?: string;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-baseline gap-4 border-b pb-2" style={{ borderColor: 'var(--rule)' }}>
        <h2 className="display text-[26px]">{title}</h2>
        {meta && <div className="ml-auto label shrink-0">{meta}</div>}
      </div>
      {note && (
        <p className="mt-2 max-w-2xl text-[11.5px]" style={{ color: 'var(--ink-faint)' }}>
          {note}
        </p>
      )}
    </div>
  );
}

export function Tag({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <span
      className="whitespace-nowrap border px-1.5 text-[9.5px] uppercase tracking-wider"
      style={{ color: color ?? 'var(--ink-faint)', borderColor: color ?? 'var(--rule-soft)' }}
    >
      {children}
    </span>
  );
}

export function StatusTag({ status, color }: { status: string; color?: string }) {
  const dot = status === 'running' ? <span className="mr-1 inline-block h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full" style={{ background: 'currentColor' }} /> : <span className="mr-1">•</span>;
  return (
    <span
      className="inline-flex items-center whitespace-nowrap border px-1.5 py-px text-[9.5px] uppercase tracking-wider"
      style={{ color: color ?? 'var(--ink-faint)', borderColor: color ?? 'var(--rule-soft)' }}
    >
      {dot}
      {status}
    </span>
  );
}

/** Collapsible section for dense secondary content. */
export function Disclose({
  summary,
  children,
  meta,
  defaultOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  meta?: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t py-2" style={{ borderColor: 'var(--rule-soft)' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-[12px]"
        aria-expanded={open}
      >
        <span style={{ color: 'var(--ink-faint)' }}>{open ? '−' : '+'}</span>
        <span className="flex-1">{summary}</span>
        {meta && <span className="label" style={{ margin: 0 }}>{meta}</span>}
      </button>
      {open && <div className="mt-2 pl-4">{children}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="m-auto max-w-md py-16 text-center">
      <p className="display text-[22px]">{title}</p>
      {children && (
        <p className="mt-3 text-[12px] leading-relaxed" style={{ color: 'var(--ink-faint)' }}>
          {children}
        </p>
      )}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % 4), 220);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="text-[11.5px]" style={{ color: 'var(--ink-faint)' }}>
      {['·  ', '·· ', '···', ' ··'][frame]} {label}
    </span>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p
      className="border-l-2 py-1 pl-2 text-[11.5px]"
      style={{ borderColor: 'var(--bad)', color: 'var(--bad)' }}
      role="alert"
    >
      {children}
    </p>
  );
}

/** Horizontal progress bar — a meter, not a rounded glow. */
export function Meter({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      className="h-[6px] w-full"
      style={{ background: 'var(--paper-sunk)', border: '1px solid var(--rule-soft)' }}
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
    >
      <div style={{ width: `${pct}%`, height: '100%', background: 'var(--brand)' }} />
    </div>
  );
}