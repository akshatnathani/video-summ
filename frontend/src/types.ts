export type Status = 'queued' | 'running' | 'ready' | 'failed';

export interface Job {
  id: string;
  url: string;
  platform: string | null;
  status: Status;
  stage: string;
  progress: number;
  error: string | null;
  title: string | null;
  duration: number | null;
  uploader: string | null;
  download_type: string;
  quality: string;
  extra?: string;
  created_at: string;
  updated_at: string;
  transcript?: Transcript;
  summary?: Summary;
  downloads?: Download[];
}

export interface Transcript {
  id: number;
  job_id: string;
  language: string | null;
  source: string;
  text: string;
  segments: Segment[];
  created_at: string;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
}

export interface Summary {
  id: number;
  job_id: string;
  eli5: string;
  detailed: string;
  key_points: string[];
  created_at: string;
}

export interface Download {
  id: number;
  job_id: string;
  type: string;
  path: string;
  size: number;
  created_at: string;
}

export interface StreamEvent {
  job_id: string;
  type: string;
  stage?: string;
  progress?: number;
  message?: string;
  data?: Record<string, unknown>;
  ts: string;
}

export interface VideoPreview {
  platform: string | null;
  title: string | null;
  uploader: string | null;
  duration: number | null;
  view_count: number | null;
  upload_date: string | null;
  thumbnail: string | null;
  captions_available: boolean;
}

export interface PlaylistEntry {
  video_id: string | null;
  url: string;
  title: string | null;
  duration: number | null;
  thumbnail: string | null;
}

export interface PlaylistPreview {
  title: string | null;
  uploader: string | null;
  entry_count: number;
  entries: PlaylistEntry[];
}

export interface CreateJobRequest {
  url: string;
  download_type: 'merged' | 'video_only' | 'audio_only';
  quality: 'best' | '1080p' | '720p' | '480p';
  extract_transcript: boolean;
  summarize: boolean;
}