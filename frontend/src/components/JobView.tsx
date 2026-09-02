import { useState } from 'react';
import type { Job } from '../types';
import {
  downloadTypeLabel,
  formatBeat,
  formatDate,
  formatDuration,
  formatFileSize,
  getOptions,
  hostOf,
  stageLabel,
} from '../lib';
import { downloadUrl } from '../api';
import type { ActivityLine } from './Pipeline';
import Pipeline from './Pipeline';
import Markdown from './Markdown';
import { ErrorNote, StatusTag, Box } from './ui';

function wordCount(text: string): number {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}

export default function JobView({
  job,
  activity,
  onSummarize,
}: {
  job: Job;
  activity: ActivityLine[];
  onSummarize: () => void;
}) {
  const opts = getOptions(job);
  const [timestamps, setTimestamps] = useState(false);
  const running = job.status === 'running' || job.status === 'queued';
  const failed = job.status === 'failed';
  const { transcript, summary, downloads } = job;

  return (
    <div className="scroll flex h-full flex-col overflow-y-auto">
      {/* title block */}
      <header
        className="border-b px-8 pb-6 pt-8"
        style={{ borderColor: 'var(--rule)', background: 'var(--paper)' }}
      >
        <div className="mx-auto max-w-3xl">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <StatusTag status={job.status} color={getStatusColor(job.status)} />
            <span style={{ color: 'var(--ink-faint)' }}>{job.platform ?? hostOf(job.url)}</span>
            <span style={{ color: 'var(--ink-faint)' }}>·</span>
            <span style={{ color: 'var(--ink-soft)' }}>{formatDuration(job.duration)}</span>
            {job.uploader && (
              <>
                <span style={{ color: 'var(--ink-faint)' }}>·</span>
                <span style={{ color: 'var(--ink-soft)' }}>{job.uploader}</span>
              </>
            )}
            <span style={{ color: 'var(--ink-faint)' }}>·</span>
            <span style={{ color: 'var(--ink-soft)' }}>
              {downloadTypeLabel(job.download_type)} / {job.quality}
            </span>
            <span className="ml-auto label" style={{ margin: 0 }}>
              added {formatDate(job.created_at)}
            </span>
          </div>

          <h1 className="display balance mt-3 text-[34px] leading-[1.05]">
            {job.title || job.url}
          </h1>

          {failed && job.error && (
            <div className="mt-4">
              <ErrorNote>{job.error}</ErrorNote>
            </div>
          )}
        </div>
      </header>

      <div className="mx-auto w-full max-w-3xl flex-1 px-8 py-6">
        {/* running → pipeline */}
        {running && (
          <Pipeline job={job} activity={activity} skipTranscript={!opts.extractTranscript} />
        )}

        {/* ready → downloads */}
        {job.status === 'ready' && downloads && downloads.length > 0 && (
          <section className="mb-8">
            <h2 className="display mb-3 text-[24px]">Download</h2>
            <div className="flex flex-wrap gap-3">
              {downloads.map((dl) => (
                <a
                  key={dl.id}
                  href={downloadUrl(job.id, dl.type)}
                  className="box box-hover inline-flex items-center gap-2 px-3 py-1.5 text-[12px]"
                >
                  <span style={{ color: 'var(--ink-faint)' }}>↓</span>
                  {downloadTypeLabel(dl.type)}
                  <span className="label" style={{ margin: 0 }}>
                    {formatFileSize(dl.size)}
                  </span>
                </a>
              ))}
            </div>
          </section>
        )}

        {/* summaries */}
        {summary && (
          <>
            <section className="mb-8">
              <div className="mb-3 flex items-baseline gap-4 border-b pb-1" style={{ borderColor: 'var(--rule)' }}>
                <h2 className="display text-[24px]">In plain words</h2>
                <span className="label ml-auto" style={{ margin: 0 }}>
                  eli5
                </span>
              </div>
              <Box strong className="p-5">
                {summary.eli5.split(/\n{2,}/).map((para, i) => (
                  <p key={i} className={i > 0 ? 'mt-3' : ''}>
                    {para}
                  </p>
                ))}
              </Box>
            </section>

            {summary.key_points.length > 0 && (
              <section className="mb-8">
                <div className="mb-3 flex items-baseline gap-4 border-b pb-1" style={{ borderColor: 'var(--rule)' }}>
                  <h2 className="display text-[24px]">Key points</h2>
                  <span className="label ml-auto" style={{ margin: 0 }}>
                    {summary.key_points.length}
                  </span>
                </div>
                <ol className="rail space-y-3">
                  {summary.key_points.map((point, i) => (
                    <li key={i} className="rail-node relative" data-state="done">
                      <p className="text-[12px] leading-relaxed">{point}</p>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section className="mb-8">
              <div className="mb-3 flex items-baseline gap-4 border-b pb-1" style={{ borderColor: 'var(--rule)' }}>
                <h2 className="display text-[24px]">Deep dive</h2>
              </div>
              <Box className="p-6">
                <Markdown text={summary.detailed} className="prose-mono max-w-none text-[12.5px]" />
              </Box>
            </section>
          </>
        )}

        {/* transcript */}
        {transcript ? (
          <section>
            <div className="mb-3 flex items-baseline border-b pb-1" style={{ borderColor: 'var(--rule)' }}>
              <h2 className="display text-[24px]">Transcript</h2>
              <span className="label ml-3" style={{ margin: 0 }}>
                {transcript.language} · {transcript.source}
              </span>
              <span className="ml-auto">
                <button
                  onClick={() => setTimestamps((v) => !v)}
                  className="nav-link text-[11px]"
                  data-active={timestamps}
                >
                  {timestamps ? 'plain' : 'timestamps'}
                </button>
              </span>
            </div>
            <div className="box scroll max-h-[440px] overflow-y-auto p-5">
              {timestamps ? (
                <ul className="space-y-2 text-[12px] leading-relaxed">
                  {transcript.segments.map((seg, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="shrink-0" style={{ color: 'var(--brand)' }}>
                        [{formatBeat(seg.start)}]
                      </span>
                      <span>{seg.text}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="whitespace-pre-wrap text-[12px] leading-relaxed">{transcript.text}</p>
              )}
            </div>
            <p className="mt-2 text-[10.5px]" style={{ color: 'var(--ink-faint)' }}>
              {wordCount(transcript.text)} words · {transcript.segments.length} segments
            </p>
          </section>
        ) : (
          job.status === 'ready' && (
            <section>
              <div className="mb-3 border-b pb-1" style={{ borderColor: 'var(--rule)' }}>
                <h2 className="display text-[24px]">Transcript</h2>
              </div>
              {opts.extractTranscript ? (
                <div>
                  <p className="max-w-2xl text-[12px]" style={{ color: 'var(--ink-soft)' }}>
                    No transcript could be produced — this video has no platform captions and no
                    useable audio track. The job itself finished successfully.
                  </p>
                </div>
              ) : (
                <p className="max-w-2xl text-[12px]" style={{ color: 'var(--ink-soft)' }}>
                  Transcript extraction was skipped for this job.
                </p>
              )}
            </section>
          )
        )}

        {/* post-hoc summarize action */}
        {job.status === 'ready' && transcript && !summary && opts.summarize && (
          <section className="box p-5">
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] font-bold">No summary generated yet</p>
                <p className="text-[11px]" style={{ color: 'var(--ink-faint)' }}>
                  The transcript is ready. Summaries are created on demand if the job skipped them.
                </p>
              </div>
              <button className="btn btn-primary shrink-0" onClick={onSummarize}>
                Summarize now
              </button>
            </div>
          </section>
        )}

        {/* failed with partial artifacts */}
        {failed && transcript && !summary && (
          <p className="border-t pt-3 text-[11px]" style={{ borderColor: 'var(--rule-soft)', color: 'var(--ink-faint)' }}>
            The job failed at {stageLabel(job.stage)} while the transcript was available —
            the transcript above is intact.
          </p>
        )}
      </div>
    </div>
  );
}

function getStatusColor(status: Job['status']): string {
  switch (status) {
    case 'ready': return 'var(--good)';
    case 'running': return 'var(--brand)';
    case 'queued': return 'var(--ink-faint)';
    case 'failed': return 'var(--bad)';
    default: return 'var(--ink-faint)';
  }
}