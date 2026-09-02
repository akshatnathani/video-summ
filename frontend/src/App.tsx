import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { deleteJob, generateSummary, getJob, getJobs, subscribeEvents } from './api';
import type { Job, StreamEvent } from './types';
import JobRail from './components/JobRail';
import JobView from './components/JobView';
import type { ActivityLine } from './components/Pipeline';
import { Empty } from './components/ui';

type Theme = 'light' | 'dark';

function readTheme(): Theme {
  return (document.documentElement.getAttribute('data-theme') as Theme) || 'light';
}

function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t);
  document.documentElement.style.colorScheme = t;
  try {
    localStorage.setItem('vs-theme', t);
  } catch {
    /* private mode */
  }
}

function themeReducer(
  state: ActivityLine[],
  action: { type: 'push'; text: string; kind: ActivityLine['kind'] } | { type: 'clear' },
): ActivityLine[] {
  if (action.type === 'clear') return [];
  const next = [...state, { id: state.length, text: action.text, kind: action.kind }];
  return next.length > 60 ? next.slice(-60) : next;
}

const PAGE_SIZE = 50;

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [totalJobs, setTotalJobs] = useState(0);
  const [selected, setSelected] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [activity, dispatchActivity] = useReducer(themeReducer, []);

  const unsubscribe = useRef<(() => void) | null>(null);
  const activeId = useRef<string | null>(null);
  const handlerRef = useRef<(e: StreamEvent) => void>(() => {});
  const listTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // How many rows are currently loaded — a background refresh re-fetches this
  // many so it doesn't silently truncate a list the user has paged through.
  const loadedCount = useRef(PAGE_SIZE);

  const refreshList = useCallback(async () => {
    try {
      const { jobs: list, total } = await getJobs({ limit: loadedCount.current });
      setJobs(list);
      setTotalJobs(total);
    } catch {
      /* keep current list on transient failure */
    }
  }, []);

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const nextLimit = loadedCount.current + PAGE_SIZE;
      const { jobs: list, total } = await getJobs({ limit: nextLimit });
      loadedCount.current = nextLimit;
      setJobs(list);
      setTotalJobs(total);
    } catch {
      /* leave the list as-is on failure */
    } finally {
      setLoadingMore(false);
    }
  }, []);

  /** Coalesce list refreshes so a burst of log events asks the gateway once. */
  const scheduleListRefresh = useCallback(() => {
    if (listTimer.current) clearTimeout(listTimer.current);
    listTimer.current = setTimeout(() => void refreshList(), 500);
  }, [refreshList]);

  const reloadSelected = useCallback(async () => {
    const id = activeId.current;
    if (!id) return;
    try {
      setSelected(await getJob(id));
    } catch {
      /* deleted while streaming — SSE close path handles it */
    }
  }, []);

  const openJob = useCallback(async (id: string) => {
    unsubscribe.current?.();
    unsubscribe.current = null;
    activeId.current = id;
    dispatchActivity({ type: 'clear' });
    let job: Job;
    try {
      job = await getJob(id);
      setSelected(job);
    } catch {
      setSelected(null);
      return;
    }
    // Terminal jobs will never emit another event — don't hold a live SSE
    // connection (and Redis subscription) open for a tab that's just reading.
    if (job.status === 'ready' || job.status === 'failed') return;
    unsubscribe.current = subscribeEvents(
      id,
      (e) => handlerRef.current(e),
      () => {
        unsubscribe.current = null;
      },
    );
  }, []);

  handlerRef.current = (e: StreamEvent) => {
    if (activeId.current && e.job_id && e.job_id !== activeId.current) return;

    if (e.message && e.type !== 'snapshot') {
      dispatchActivity({
        type: 'push',
        text: e.message,
        kind: e.type.endsWith('.failed') ? 'error' : 'log',
      });
    }

    if (e.type === 'snapshot') {
      void reloadSelected();
      return;
    }

    if (e.type === 'stage.started' || e.type === 'log') {
      setSelected((prev) =>
        prev ? { ...prev, stage: e.stage ?? prev.stage, progress: e.progress ?? prev.progress } : prev,
      );
      scheduleListRefresh();
      return;
    }

    if (e.type === 'artifact.ready' || e.type === 'job.ready' || e.type === 'job.failed') {
      void reloadSelected();
      scheduleListRefresh();
    }
  };

  const handleCreated = useCallback(async (job: Job) => {
    await refreshList();
    await openJob(job.id);
  }, [refreshList, openJob]);

  const handleBatchCreated = useCallback(async (jobs: Job[]) => {
    await refreshList();
    if (jobs.length > 0) await openJob(jobs[0].id);
  }, [refreshList, openJob]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (activeId.current === id) {
        unsubscribe.current?.();
        unsubscribe.current = null;
        activeId.current = null;
        setSelected(null);
      }
      await deleteJob(id).catch(() => undefined);
      const list = await getJobs({ limit: loadedCount.current }).catch(() => ({
        jobs: [] as Job[],
        total: 0,
      }));
      setJobs(list.jobs);
      setTotalJobs(list.total);
      if (list.jobs.length > 0) await openJob(list.jobs[0].id);
    },
    [openJob],
  );

  const handleSummarize = useCallback(async () => {
    const id = activeId.current;
    if (!id) return;
    try {
      await generateSummary(id);
      await reloadSelected();
      dispatchActivity({ type: 'push', text: 'Summary generated on demand.', kind: 'log' });
    } catch (err) {
      dispatchActivity({
        type: 'push',
        text: err instanceof Error ? err.message : 'Could not summarize.',
        kind: 'error',
      });
    }
  }, [reloadSelected]);

  useEffect(() => {
    void (async () => {
      const { jobs: list, total } = await getJobs({ limit: loadedCount.current });
      setJobs(list);
      setTotalJobs(total);
      if (list.length > 0) await openJob(list[0].id);
      setLoading(false);
    })();
    return () => {
      unsubscribe.current?.();
      if (listTimer.current) clearTimeout(listTimer.current);
    };
  }, [openJob]);

  const runningCount = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;
  const readyCount = jobs.filter((j) => j.status === 'ready').length;

  return (
    <div className="flex h-screen overflow-hidden">
      <JobRail
        jobs={jobs}
        total={totalJobs}
        loadingMore={loadingMore}
        onLoadMore={loadMore}
        selectedId={selected?.id ?? null}
        onSelect={openJob}
        onCreated={handleCreated}
        onBatchCreated={handleBatchCreated}
        onDelete={handleDelete}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex items-baseline gap-x-6 border-b px-8 py-5"
          style={{ borderColor: 'var(--rule)' }}
        >
          <h1 className="display text-[30px] leading-none">
            Summarize
            <span className="ml-1.5 align-super text-[13px]" style={{ color: 'var(--brand)' }}>
              ▲
            </span>
          </h1>
          <p className="hidden text-[11px] md:block" style={{ color: 'var(--ink-faint)' }}>
            videos → transcripts → plain-language summaries
          </p>

          <div className="ml-auto flex items-center gap-4 text-[11px]">
            <span className="label" style={{ margin: 0 }}>
              {runningCount > 0 ? (
                <span className="inline-flex items-center gap-1.5" style={{ color: 'var(--brand)' }}>
                  <span className="inline-block h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full" style={{ background: 'currentColor' }} />
                  {runningCount}&nbsp;processing
                </span>
              ) : (
                `${readyCount} ready · ${jobs.length} total`
              )}
            </span>
            <button
              className="btn"
              onClick={() => {
                const next: Theme = theme === 'dark' ? 'light' : 'dark';
                setTheme(next);
                applyTheme(next);
              }}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? '☀ light' : '◐ dark'}
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          {loading ? (
            <Empty title="Opening the studio…" />
          ) : selected ? (
            <JobView job={selected} activity={activity} onSummarize={handleSummarize} />
          ) : (
            <Landing onCreate={() => document.querySelector<HTMLInputElement>('input[aria-label="Video URL"]')?.focus()} />
          )}
        </div>
      </main>
    </div>
  );
}

function Landing({ onCreate }: { onCreate: () => void }) {
  const path = [
    ['Download', 'Best-available media is fetched from YouTube or Instagram.'],
    ['Transcribe', 'Platform captions first — instant. Local speech-to-text only when a video has none.'],
    ['Explain', 'An ELI5 take, key points with timestamps, and a full deep dive.'],
  ];

  return (
    <div className="scroll h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-16">
        <h2 className="display balance text-[46px] leading-[1.05]">
          A video, minus the noise. A transcript and a plain-language summary.
        </h2>
        <p className="mt-5 max-w-xl text-[13px] leading-relaxed" style={{ color: 'var(--ink-soft)' }}>
          Paste a link, wait a minute, read the gist. Every job keeps its media, its
          transcript and its summaries together — download any of them afterwards.
        </p>

        <button onClick={onCreate} className="btn btn-primary mt-8">
          Add your first video →
        </button>

        <ol className="rail mt-14 space-y-7">
          {path.map(([name, detail]) => (
            <li key={name} className="rail-node relative" data-state="done">
              <h3 className="text-[12.5px] font-bold">{name}</h3>
              <p className="mt-1 max-w-xl text-[12px]" style={{ color: 'var(--ink-soft)' }}>
                {detail}
              </p>
            </li>
          ))}
        </ol>

        <p
          className="mt-14 border-t pt-4 text-[11px] italic"
          style={{ borderColor: 'var(--rule-soft)', color: 'var(--ink-faint)' }}
        >
          Summaries are generated by an LLM from the transcript — read them as a starting
          point, not a transcript replacement.
        </p>
      </div>
    </div>
  );
}