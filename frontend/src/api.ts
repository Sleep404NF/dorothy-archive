export type JobStatus = "queued" | "tagging" | "generating" | "done" | "failed";

export interface Job {
  id: string;
  created_at: string;
  rerun_of: string | null;
  status: JobStatus;
  request: string | null;
  tags: Record<string, string[]> | null;
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
  return res.json() as Promise<T>;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  listJobs: (limit: number) => call<JobPage>(`/jobs?limit=${limit}`),
  createJob: (input: JobInput) => call<Job>("/jobs", post(input)),
  rerun: (id: string, newSeed: boolean) => call<Job>(`/jobs/${id}/rerun?new_seed=${newSeed}`, post()),
  imageUrl: (job: Job) => (job.image_url ? BASE + job.image_url : null),
};

export const isActive = (job: Job) =>
  job.status === "queued" || job.status === "tagging" || job.status === "generating";

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "대기 중",
  tagging: "태그 변환 중",
  generating: "그리는 중",
  done: "완료",
  failed: "실패",
};
