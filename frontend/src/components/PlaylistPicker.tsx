import { useMemo, useState } from 'react';
import { createJobsBatch, MAX_BATCH_JOBS, type CreateJobInput } from '../api';
import type { Job, PlaylistPreview } from '../types';
import { formatDuration } from '../lib';
import { ErrorNote } from './ui';

export default function PlaylistPicker({
  preview,
  downloadType,
  quality,
  extractTranscript,
  summarize,
  onClose,
  onCreated,
}: {
  preview: PlaylistPreview;
  downloadType: CreateJobInput['download_type'];
  quality: CreateJobInput['quality'];
  extractTranscript: boolean;
  summarize: boolean;
  onClose: () => void;
  onCreated: (jobs: Job[]) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(preview.entries.slice(0, MAX_BATCH_JOBS).map((e) => e.url)),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const overLimit = selected.size > MAX_BATCH_JOBS;

  const toggle = (url: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(preview.entries.map((e) => e.url)));
  const selectNone = () => setSelected(new Set());

  const totalDuration = useMemo(
    () =>
      preview.entries
        .filter((e) => selected.has(e.url))
        .reduce((sum, e) => sum + (e.duration ?? 0), 0),
    [preview.entries, selected],
  );

  const submit = async () => {
    if (selected.size === 0 || overLimit || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { jobs } = await createJobsBatch({
        urls: [...selected],
        download_type: downloadType,
        quality,
        extract_transcript: extractTranscript,
        summarize,
      });
      onCreated(jobs);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add these videos.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="box-strong flex max-h-[80vh] w-full max-w-lg flex-col"
        style={{ background: 'var(--paper)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b p-5" style={{ borderColor: 'var(--rule)' }}>
          <div className="min-w-0">
            <p className="display text-[20px] leading-tight">{preview.title || 'Playlist'}</p>
            <p className="label mt-1" style={{ margin: 0 }}>
              {preview.uploader ? `${preview.uploader} · ` : ''}
              {preview.entry_count} video{preview.entry_count === 1 ? '' : 's'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-[16px]"
            style={{ color: 'var(--ink-faint)' }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex items-center gap-3 border-b px-5 py-2.5" style={{ borderColor: 'var(--rule-soft)' }}>
          <button type="button" onClick={selectAll} className="nav-link text-[11px]">
            All
          </button>
          <button type="button" onClick={selectNone} className="nav-link text-[11px]">
            None
          </button>
          <span className="label ml-auto" style={{ margin: 0 }}>
            {selected.size} selected{totalDuration > 0 ? ` · ${formatDuration(totalDuration)} total` : ''}
          </span>
        </div>

        <ul className="scroll flex-1 overflow-y-auto p-2">
          {preview.entries.map((entry) => {
            const checked = selected.has(entry.url);
            return (
              <li key={entry.url}>
                <label
                  className="flex cursor-pointer items-center gap-2.5 p-2 text-left"
                  style={{ background: checked ? 'var(--paper-sunk)' : 'transparent' }}
                >
                  <input
                    type="checkbox"
                    className="check shrink-0"
                    checked={checked}
                    onChange={() => toggle(entry.url)}
                  />
                  {entry.thumbnail ? (
                    <img
                      src={entry.thumbnail}
                      alt=""
                      className="h-10 w-16 shrink-0 object-cover"
                      style={{ background: 'var(--paper-sunk)' }}
                    />
                  ) : (
                    <div className="h-10 w-16 shrink-0" style={{ background: 'var(--paper-sunk)' }} />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-1 text-[11.5px] leading-snug">{entry.title || entry.url}</p>
                    <p className="label mt-0.5" style={{ margin: 0 }}>
                      {formatDuration(entry.duration)}
                    </p>
                  </div>
                </label>
              </li>
            );
          })}
        </ul>

        <div className="border-t p-4" style={{ borderColor: 'var(--rule)' }}>
          {error && (
            <div className="mb-2">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}
          {overLimit && (
            <div className="mb-2">
              <ErrorNote>Pick up to {MAX_BATCH_JOBS} at a time — you have {selected.size} selected.</ErrorNote>
            </div>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="btn flex-1">
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={selected.size === 0 || overLimit || busy}
              className="btn btn-primary flex-1"
            >
              {busy ? 'Queuing…' : `Download ${selected.size || ''} video${selected.size === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
