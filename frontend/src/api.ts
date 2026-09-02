import type { Job, PlaylistPreview, StreamEvent, VideoPreview } from './types';

const API_BASE = '/api';

export const MAX_BATCH_JOBS = 25;

export interface CreateJobInput {
  url: string;
  download_type: 'merged' | 'video_only' | 'audio_only';
  quality: 'best' | '1080p' | '720p' | '480p';
  extract_transcript: boolean;
  summarize: boolean;
}

export async function createJob(data: CreateJobInput) {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Create many jobs at once (e.g. videos picked from a playlist) — the ingest
 * workers pull them off the queue concurrently, so this is what runs them in parallel. */
export async function createJobsBatch(data: {
  urls: string[];
  download_type: CreateJobInput['download_type'];
  quality: CreateJobInput['quality'];
  extract_transcript: boolean;
  summarize: boolean;
}): Promise<{ jobs: Job[] }> {
  const res = await fetch(`${API_BASE}/jobs/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Metadata-only lookup (no download) — used to preview a pasted URL before committing to a job. */
export async function previewVideo(url: string, signal?: AbortSignal): Promise<VideoPreview> {
  const res = await fetch(`${API_BASE}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
    signal,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Lists a playlist's videos (no download) so the UI can offer a pick list. */
export async function previewPlaylist(url: string, signal?: AbortSignal): Promise<PlaylistPreview> {
  const res = await fetch(`${API_BASE}/playlist/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
    signal,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJobs(
  params: { limit?: number; offset?: number } = {},
): Promise<{ jobs: Job[]; total: number }> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : '';
  const res = await fetch(`${API_BASE}/jobs${suffix}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJob(id: string) {
  const res = await fetch(`${API_BASE}/jobs/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteJob(id: string) {
  const res = await fetch(`${API_BASE}/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateSummary(id: string, force = false) {
  const res = await fetch(`${API_BASE}/jobs/${id}/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function downloadUrl(id: string, type: string): string {
  return `${API_BASE}/jobs/${id}/download/${type}`;
}

const TERMINAL_EVENTS = new Set(['job.ready', 'job.failed']);
const MAX_RETRY_DELAY_MS = 15000;

/**
 * Subscribes to a job's SSE stream and reconnects with backoff on transient
 * drops (a plain `es.close()` on error would otherwise permanently kill the
 * live feed on any network blip). Stops for good once the job reaches a
 * terminal state — either via an explicit event or the reconnect snapshot.
 */
export function subscribeEvents(
  jobId: string,
  onEvent: (e: StreamEvent) => void,
  onClose: () => void,
): () => void {
  let es: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let retryDelay = 1000;
  let stopped = false;

  const finish = () => {
    if (stopped) return;
    stopped = true;
    if (retryTimer) clearTimeout(retryTimer);
    es?.close();
    es = null;
    onClose();
  };

  const connect = () => {
    es = new EventSource(`${API_BASE}/jobs/${jobId}/events`);
    es.onopen = () => {
      retryDelay = 1000;
    };
    es.onmessage = (e) => {
      let event: StreamEvent & { job?: { status?: string } };
      try {
        event = JSON.parse(e.data);
      } catch {
        return; // ignore malformed frames
      }
      onEvent(event);
      const snapshotStatus = event.type === 'snapshot' ? event.job?.status : undefined;
      if (
        TERMINAL_EVENTS.has(event.type) ||
        snapshotStatus === 'ready' ||
        snapshotStatus === 'failed'
      ) {
        finish();
      }
    };
    es.onerror = () => {
      es?.close();
      es = null;
      if (stopped) return;
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS);
    };
  };

  connect();
  return finish;
}