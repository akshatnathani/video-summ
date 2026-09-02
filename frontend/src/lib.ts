import type { Status } from './types';

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return '--:--';
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

export function formatBeat(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '--:--';
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0) return '?';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function formatDate(ts: string | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** The pipeline, in order. `transcript` may be skipped on purpose. */
export const STAGE_FLOW = [
  { key: 'queued', label: 'Received' },
  { key: 'info', label: 'Fetching info' },
  { key: 'downloading', label: 'Downloading' },
  { key: 'transcript', label: 'Transcribing' },
  { key: 'summarize', label: 'Summarizing' },
  { key: 'ready', label: 'Ready' },
] as const;

export type StageKey = (typeof STAGE_FLOW)[number]['key'];

export function stageLabel(stage: string | null | undefined): string {
  return STAGE_FLOW.find((s) => s.key === stage)?.label ?? stage ?? '…';
}

export const STATUS_META: Record<Status, { label: string; color: string }> = {
  queued: { label: 'queued', color: 'var(--ink-faint)' },
  running: { label: 'running', color: 'var(--brand)' },
  ready: { label: 'ready', color: 'var(--good)' },
  failed: { label: 'failed', color: 'var(--bad)' },
};

export function statusColor(status: Status | string): string {
  return STATUS_META[(status as Status) ?? 'queued']?.color ?? 'var(--ink-faint)';
}

export function statusLabel(status: Status | string): string {
  return STATUS_META[(status as Status) ?? 'queued']?.label ?? status;
}

export function downloadTypeLabel(type: string): string {
  switch (type) {
    case 'merged': return 'Video + audio';
    case 'video_only': return 'Video only';
    case 'audio_only': return 'Audio only';
    default: return type.replace(/_/g, ' ');
  }
}

export function qualityLabel(q: string): string {
  return q === 'best' ? 'best' : q;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export function getOptions(job: { extra?: string }) {
  let extra: Record<string, unknown> = {};
  if (job.extra) {
    try {
      extra = JSON.parse(job.extra);
    } catch {
      extra = {};
    }
  }
  return {
    extractTranscript: extra.extract_transcript !== false,
    summarize: extra.summarize !== false,
  };
}

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}