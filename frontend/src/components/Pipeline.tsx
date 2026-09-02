import { STAGE_FLOW, stageLabel } from '../lib';
import type { Job } from '../types';
import { Label, Meter } from './ui';

export interface ActivityLine {
  id: number;
  text: string;
  kind: 'log' | 'error';
}

export default function Pipeline({
  job,
  activity,
  skipTranscript,
}: {
  job: Job;
  activity: ActivityLine[];
  skipTranscript: boolean;
}) {
  const failed = job.status === 'failed';
  const current = job.stage;
  const idx = Math.max(0, STAGE_FLOW.findIndex((s) => s.key === current));

  return (
    <div className="box p-5">
      <div className="flex items-baseline gap-4">
        <Label>Pipeline</Label>
        <span className="ml-auto label" style={{ margin: 0 }}>
          {Math.round(job.progress * 100)}%
        </span>
      </div>

      <div className="mt-4">
        <Meter value={Math.round(job.progress * 100)} />
      </div>

      <ol className="rail mt-4 space-y-2.5">
        {STAGE_FLOW.map((s) => {
          const i = STAGE_FLOW.findIndex((x) => x.key === s.key);
          const state = failed
            ? i === idx
              ? 'failed'
              : i < idx
                ? 'done'
                : 'idle'
            : i < idx
              ? 'done'
              : i === idx
                ? 'active'
                : 'idle';

          const pendingSkip =
            s.key === 'transcript' && skipTranscript && job.status !== 'failed';

          return (
            <li
              key={s.key}
              className="rail-node relative flex items-baseline justify-between"
              data-state={pendingSkip ? 'idle' : state}
            >
              <span className={`text-[12px] ${i === idx && !failed ? 'font-bold' : ''}`}>
                {s.label}
              </span>
              <span className="label" style={{ margin: 0 }}>
                {pendingSkip
                  ? 'skipped'
                  : state === 'done'
                    ? 'done'
                    : state === 'failed'
                      ? 'failed'
                      : i === idx && !failed
                        ? 'now'
                        : '…'}
              </span>
            </li>
          );
        })}
      </ol>

      <div className="mt-4 border-t pt-3" style={{ borderColor: 'var(--rule-soft)' }}>
        <Label>Feed</Label>
        {activity.length === 0 ? (
          <p className="mt-1.5 text-[11px]" style={{ color: 'var(--ink-faint)' }}>
            {stageLabel(job.stage)}…
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {[...activity].reverse().map((line) => (
              <li
                key={line.id}
                className="rise text-[10.5px] leading-snug"
                style={{ color: line.kind === 'error' ? 'var(--bad)' : 'var(--ink-soft)' }}
              >
                <span style={{ color: 'var(--ink-faint)' }}>› </span>
                {line.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}