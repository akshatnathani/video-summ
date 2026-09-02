import type { Job } from '../types';
import { formatDate, formatDuration, hostOf, stageLabel, statusColor } from '../lib';
import { Label } from './ui';
import NewJobForm from './NewJobForm';

function StateDot({ job }: { job: Job }) {
  const color = statusColor(job.status);
  if (job.status === 'ready') {
    return (
      <span className="w-[13px] shrink-0 pt-0.5 text-[10px] leading-none" style={{ color: 'var(--good)' }}>
        ✓
      </span>
    );
  }
  if (job.status === 'failed') {
    return (
      <span className="w-[13px] shrink-0 pt-0.5 text-[10px] leading-none" style={{ color: 'var(--bad)' }}>
        ✕
      </span>
    );
  }
  if (job.status === 'running') {
    return (
      <span className="flex w-[13px] shrink-0 justify-center pt-1">
        <span
          className="h-[7px] w-[7px] animate-[pulse_1.5s_ease-in-out_infinite] rounded-full"
          style={{ background: color }}
        />
      </span>
    );
  }
  return (
    <span className="flex w-[13px] shrink-0 justify-center pt-1">
      <span
        className="h-[7px] w-[7px] rounded-full border"
        style={{ borderColor: color, background: 'transparent' }}
      />
    </span>
  );
}

export default function JobRail({
  jobs,
  total,
  loadingMore,
  onLoadMore,
  selectedId,
  onSelect,
  onCreated,
  onBatchCreated,
  onDelete,
}: {
  jobs: Job[];
  total: number;
  loadingMore: boolean;
  onLoadMore: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreated: (job: Job) => void;
  onBatchCreated: (jobs: Job[]) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside
      className="scroll flex w-[300px] shrink-0 flex-col overflow-y-auto border-r"
      style={{ borderColor: 'var(--rule)', background: 'var(--paper-sunk)' }}
    >
      <div className="border-b p-5" style={{ borderColor: 'var(--rule-soft)' }}>
        <NewJobForm onCreated={onCreated} onBatchCreated={onBatchCreated} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col p-5">
        <Label>
          Library
          <span className="ml-2">({jobs.length})</span>
        </Label>
        {jobs.length === 0 ? (
          <p className="mt-3 text-[11px]" style={{ color: 'var(--ink-faint)' }}>
            Nothing here yet. Paste a video link above and it will be queued, downloaded,
            transcribed and summarized.
          </p>
        ) : (
          <ol className="mt-3 space-y-0.5">
            {jobs.map((job) => {
              const active = job.id === selectedId;
              return (
                <li
                  key={job.id}
                  className="group flex items-start gap-2 border-b border-l-2 border-transparent py-1.5 pl-[11px]"
                  style={
                    active
                      ? { borderLeftColor: 'var(--rule)', borderBottomColor: 'var(--rule-soft)' }
                      : { borderBottomColor: 'var(--rule-soft)' }
                  }
                >
                  <StateDot job={job} />
                  <button
                    onClick={() => onSelect(job.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <p
                      className="line-clamp-2 text-[11.5px] leading-snug"
                      style={{ color: active ? 'var(--ink)' : 'var(--ink-soft)' }}
                    >
                      {active && '▸ '}
                      {job.title || job.url}
                    </p>
                    <p className="label mt-0.5" style={{ margin: 0 }}>
                      {job.status === 'running'
                        ? `${stageLabel(job.stage)} · ${Math.round(job.progress * 100)}%`
                        : `${job.status} · ${formatDuration(job.duration)} · ${job.platform ?? hostOf(job.url)} · ${formatDate(job.created_at)}`}
                    </p>
                  </button>
                  <button
                    onClick={() => {
                      if (confirm('Delete this job and all of its files?')) onDelete(job.id);
                    }}
                    className="shrink-0 px-1 opacity-0 transition group-hover:opacity-100"
                    style={{ color: 'var(--ink-faint)' }}
                    aria-label="Delete job"
                    title="Delete job"
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {jobs.length < total && (
          <button
            onClick={onLoadMore}
            disabled={loadingMore}
            className="btn mt-3 w-full"
            style={{ fontSize: '11px' }}
          >
            {loadingMore ? 'Loading…' : `Load more (${total - jobs.length} older)`}
          </button>
        )}
      </div>
    </aside>
  );
}