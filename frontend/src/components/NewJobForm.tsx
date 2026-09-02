import { useEffect, useRef, useState } from 'react';
import { createJob, previewPlaylist, previewVideo, type CreateJobInput } from '../api';
import type { Job, PlaylistPreview, VideoPreview } from '../types';
import { formatDuration } from '../lib';
import { Label, ErrorNote } from './ui';
import PlaylistPicker from './PlaylistPicker';

const ALLOWED_HOSTS = new Set([
  'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be',
  'instagram.com', 'www.instagram.com',
]);

function parseAllowed(raw: string): URL | null {
  try {
    const u = new URL(raw);
    return u.protocol === 'https:' && ALLOWED_HOSTS.has(u.hostname.toLowerCase()) ? u : null;
  } catch {
    return null;
  }
}

function looksLikePlaylist(u: URL): boolean {
  if (u.hostname.toLowerCase().includes('instagram')) return false;
  return u.searchParams.has('list') || u.pathname.replace(/\/$/, '').endsWith('/playlist');
}

export default function NewJobForm({
  onCreated,
  onBatchCreated,
}: {
  onCreated: (job: Job) => void;
  onBatchCreated: (jobs: Job[]) => void;
}) {
  const [url, setUrl] = useState('');
  const [downloadType, setDownloadType] = useState<CreateJobInput['download_type']>('merged');
  const [quality, setQuality] = useState<CreateJobInput['quality']>('best');
  const [extractTranscript, setExtractTranscript] = useState(true);
  const [summarize, setSummarize] = useState(true);
  const [options, setOptions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [preview, setPreview] = useState<VideoPreview | null>(null);
  const [playlistPreview, setPlaylistPreview] = useState<PlaylistPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const previewAbort = useRef<AbortController | null>(null);

  const isPlaylist = !!parseAllowed(url.trim()) && looksLikePlaylist(parseAllowed(url.trim())!);

  // As soon as the pasted text looks like a YouTube/Instagram link, look up
  // its title/duration/etc. (or, for a playlist link, its video list) — no
  // download happens until the user explicitly commits.
  useEffect(() => {
    previewAbort.current?.abort();
    setPreview(null);
    setPlaylistPreview(null);
    setPreviewError(null);

    const trimmed = url.trim();
    const parsed = parseAllowed(trimmed);
    if (!parsed) {
      setPreviewLoading(false);
      return;
    }
    const playlist = looksLikePlaylist(parsed);

    setPreviewLoading(true);
    const debounce = setTimeout(() => {
      const controller = new AbortController();
      previewAbort.current = controller;
      const lookup = playlist ? previewPlaylist(trimmed, controller.signal) : previewVideo(trimmed, controller.signal);
      lookup
        .then((info) => {
          if (playlist) setPlaylistPreview(info as PlaylistPreview);
          else setPreview(info as VideoPreview);
          setPreviewLoading(false);
        })
        .catch((err) => {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          setPreviewError(err instanceof Error ? err.message : 'Could not look up this link.');
          setPreviewLoading(false);
        });
    }, 450);

    return () => clearTimeout(debounce);
  }, [url]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || busy || isPlaylist) return;
    setBusy(true);
    setError(null);
    try {
      const job = await createJob({
        url: url.trim(),
        download_type: downloadType,
        quality,
        extract_transcript: extractTranscript,
        summarize,
      });
      setUrl('');
      setPreview(null);
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create job.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Label>New video</Label>
      <input
        className="field"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Paste a YouTube/Instagram video or playlist URL…"
        aria-label="Video URL"
        autoFocus
      />
      {error && <ErrorNote>{error}</ErrorNote>}

      {previewLoading && (
        <p className="text-[11px]" style={{ color: 'var(--ink-faint)' }}>
          Looking up {isPlaylist ? 'playlist' : 'video'}…
        </p>
      )}
      {previewError && <ErrorNote>{previewError}</ErrorNote>}

      {preview && !previewLoading && (
        <div className="box flex gap-2.5 p-2">
          {preview.thumbnail ? (
            <img
              src={preview.thumbnail}
              alt=""
              className="h-14 w-24 shrink-0 object-cover"
              style={{ background: 'var(--paper-sunk)' }}
            />
          ) : (
            <div className="h-14 w-24 shrink-0" style={{ background: 'var(--paper-sunk)' }} />
          )}
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 text-[11.5px] leading-snug">{preview.title || url}</p>
            <p className="label mt-1" style={{ margin: 0 }}>
              {[
                preview.uploader,
                formatDuration(preview.duration),
                preview.view_count != null ? `${preview.view_count.toLocaleString()} views` : null,
                preview.captions_available ? 'captions' : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
        </div>
      )}

      {playlistPreview && !previewLoading && (
        <div className="box flex items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="line-clamp-1 text-[11.5px] font-bold leading-snug">{playlistPreview.title || 'Playlist'}</p>
            <p className="label mt-0.5" style={{ margin: 0 }}>
              {playlistPreview.uploader ? `${playlistPreview.uploader} · ` : ''}
              {playlistPreview.entry_count} video{playlistPreview.entry_count === 1 ? '' : 's'}
            </p>
          </div>
          <button type="button" onClick={() => setPickerOpen(true)} className="btn btn-primary shrink-0">
            Choose videos →
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOptions((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-[11px]"
        style={{ color: 'var(--ink-soft)' }}
        aria-expanded={options}
      >
        <span style={{ color: 'var(--ink-faint)' }}>{options ? '−' : '+'}</span>
        <span className="flex-1">Options</span>
        <span className="label" style={{ margin: 0 }}>
          {downloadType} · {quality}
        </span>
      </button>

      {options && (
        <div className="space-y-3 border-t pt-3" style={{ borderColor: 'var(--rule-soft)' }}>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <Label>Download</Label>
              <select
                className="field mt-1 !py-1.5 text-[11.5px]"
                value={downloadType}
                onChange={(e) => setDownloadType(e.target.value as CreateJobInput['download_type'])}
              >
                <option value="merged">Video + audio</option>
                <option value="video_only">Video only</option>
                <option value="audio_only">Audio only</option>
              </select>
            </label>
            <label className="block">
              <Label>Quality</Label>
              <select
                className="field mt-1 !py-1.5 text-[11.5px]"
                value={quality}
                onChange={(e) => setQuality(e.target.value as CreateJobInput['quality'])}
              >
                <option value="best">Best</option>
                <option value="1080p">1080p</option>
                <option value="720p">720p</option>
                <option value="480p">480p</option>
              </select>
            </label>
          </div>
          <label className="flex items-center gap-2 text-[11.5px]">
            <input
              type="checkbox"
              className="check"
              checked={extractTranscript}
              onChange={(e) => setExtractTranscript(e.target.checked)}
            />
            Extract transcript
          </label>
          <label className="flex items-center gap-2 text-[11.5px]">
            <input
              type="checkbox"
              className="check"
              checked={summarize}
              onChange={(e) => setSummarize(e.target.checked)}
            />
            Generate summary
          </label>
        </div>
      )}

      {!isPlaylist && (
        <button className="btn btn-primary w-full" disabled={!url.trim() || busy}>
          {busy ? 'Queuing…' : 'Add video'}
        </button>
      )}

      {pickerOpen && playlistPreview && (
        <PlaylistPicker
          preview={playlistPreview}
          downloadType={downloadType}
          quality={quality}
          extractTranscript={extractTranscript}
          summarize={summarize}
          onClose={() => setPickerOpen(false)}
          onCreated={(jobs) => {
            setUrl('');
            setPlaylistPreview(null);
            onBatchCreated(jobs);
          }}
        />
      )}
    </form>
  );
}
