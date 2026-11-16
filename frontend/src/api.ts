export type JobStatus = "queued" | "tagging" | "generating" | "done" | "failed";
export type PresetType = "character" | "style";

export interface PresetInput {
  type: PresetType;
  name: string;
  positive: string[];
  negative: string[];
}

export interface Preset extends PresetInput {
  id: string;
  lora: unknown[];
  created_at: string;
  updated_at: string;
}

export interface TagReport {
  glossary?: { term: string; added: string[]; removed: string[] }[];
  aliased?: { from: string; to: string }[];
  dropped?: string[];
}

export interface Composed {
  positive: string;
  negative_tags: string[];
}

export interface Job {
  id: string;
  created_at: string;
  rerun_of: string | null;
  status: JobStatus;
  request: string | null;
  tags: Record<string, string[]> | null;
  presets: Partial<Record<PresetType, Preset>> | null;
  tag_report: TagReport | null;
  positive: string | null;
  negative: string;
  seed: number;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  backend: string;
  image_url: string | null;
  error: string | null;
  tagging_seconds: number | null;
  generation_seconds: number | null;
}

export interface JobPage {
  total: number;
  items: Job[];
}

export interface JobInput {
  request?: string;
  prompt?: string;
  character_preset_id?: string;
  style_preset_id?: string;
  exclude_nsfw: boolean;
  seed?: number;
  width: number;
  height: number;
  steps: number;
}

const BASE = "/api";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new Error("백엔드에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const text = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg).join(", ")
      : (detail ?? res.statusText);
    throw new Error(res.status >= 500 ? `백엔드 오류 (${res.status}): ${text}` : String(text));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});
const post = (body?: unknown) => send("POST", body);

export const api = {
  listJobs: (limit: number) => call<JobPage>(`/jobs?limit=${limit}`),
  createJob: (input: JobInput) => call<Job>("/jobs", post(input)),
  rerun: (id: string, newSeed: boolean) => call<Job>(`/jobs/${id}/rerun?new_seed=${newSeed}`, post()),
  imageUrl: (job: Job) => (job.image_url ? BASE + job.image_url : null),

  listPresets: () => call<Preset[]>("/presets"),
  createPreset: (input: PresetInput) => call<Preset>("/presets", post(input)),
  updatePreset: (id: string, input: PresetInput) => call<Preset>(`/presets/${id}`, send("PUT", input)),
  deletePreset: (id: string) => call<void>(`/presets/${id}`, send("DELETE")),
  composePresets: (body: { character_preset_id?: string; style_preset_id?: string; prompt?: string }) =>
    call<Composed>("/presets/compose", post(body)),
};

export const PRESET_TYPE_LABEL: Record<PresetType, string> = {
  character: "캐릭터",
  style: "스타일",
};

/** "1girl, silver hair" 같은 쉼표 구분 문자열을 태그 배열로 바꾼다. */
export const splitTags = (text: string) =>
  text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

export interface Progress {
  step: number;
  total: number;
}

/**
 * 서버가 보내는 작업 이벤트(SSE)를 구독한다. 끊기면 브라우저가 알아서 다시 붙는다.
 * 돌려주는 함수를 부르면 구독을 끝낸다.
 */
export function subscribeEvents(handlers: {
  onJob: (job: Job) => void;
  onProgress: (id: string, progress: Progress) => void;
  onConnection: (open: boolean) => void;
}): () => void {
  const source = new EventSource(`${BASE}/events`);
  source.onopen = () => handlers.onConnection(true);
  source.onerror = () => handlers.onConnection(false);
  source.addEventListener("job", (e) => handlers.onJob(JSON.parse((e as MessageEvent).data).job));
  source.addEventListener("progress", (e) => {
    const { id, step, total } = JSON.parse((e as MessageEvent).data);
    handlers.onProgress(id, { step, total });
  });
  return () => source.close();
}

export const isActive = (job: Job) =>
  job.status === "queued" || job.status === "tagging" || job.status === "generating";

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "대기 중",
  tagging: "태그 변환 중",
  generating: "그리는 중",
  done: "완료",
  failed: "실패",
};
