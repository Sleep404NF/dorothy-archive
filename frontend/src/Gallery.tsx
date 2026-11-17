import { useEffect, useMemo, useState } from "react";
import { api, isActive, STATUS_LABEL, type Job, type Progress } from "./api";

function useNow(enabled: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [enabled]);
  return now;
}

export const caption = (job: Job) => job.request ?? job.positive ?? "";

// 카드에는 최종 프롬프트를 태그로 보여 준다. 품질 태그는 모든 그림에 붙어서 구분에 도움이 안 되므로 뺀다.
const QUALITY_TAGS = new Set(["masterpiece", "best quality", "newest", "absurdres", "highres"]);

/** "(white jacket:1.2)" -> "white jacket", "kei \(blue archive\)" -> "kei (blue archive)" */
function readableTag(raw: string): string {
  const tag = raw.trim();
  const weighted = tag.match(/^\((.+):[\d.]+\)$/);
  return (weighted ? weighted[1] : tag).replace(/\\([()])/g, "$1").trim();
}

/** 한국어로 요청했든 태그로 넣었든, 그림에 실제로 쓰인 태그를 돌려준다. 아직 태그 변환 전이면 빈 배열. */
export function displayTags(job: Job): string[] {
  if (!job.positive) return [];
  return job.positive
    .split(",")
    .map((t) => readableTag(t))
    .filter((t) => t && !QUALITY_TAGS.has(t));
}

// DB 에는 UTC 로 저장돼 있고, 화면에서는 브라우저의 로컬 시간(한국 시간) 기준으로 묶는다.
const DAY_FORMAT = new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric", weekday: "short" });

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

function dayLabel(day: Date, today: Date): string {
  const diff = Math.round((startOfDay(today) - startOfDay(day)) / 86_400_000);
  if (diff === 0) return "오늘";
  if (diff === 1) return "어제";
  const label = DAY_FORMAT.format(day);
  return day.getFullYear() === today.getFullYear() ? label : `${day.getFullYear()}년 ${label}`;
}

interface DayGroup {
  key: string;
  label: string;
  jobs: Job[];
}

/** 최신순으로 받은 기록을 로컬 날짜별로 묶는다. 순서는 그대로 유지한다. */
function groupByDay(jobs: Job[], today: Date): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const job of jobs) {
    const created = new Date(job.created_at);
    const key = `${created.getFullYear()}-${created.getMonth() + 1}-${created.getDate()}`;
    const last = groups[groups.length - 1];
    if (last?.key === key) last.jobs.push(job);
    else groups.push({ key, label: dayLabel(created, today), jobs: [job] });
  }
  return groups;
}

interface Props {
  jobs: Job[];
  progress: Record<string, Progress>;
  onSelect: (id: string) => void;
}

export function Gallery({ jobs, progress, onSelect }: Props) {
  const now = useNow(jobs.some(isActive));
  const today = new Date(now).toDateString();
  const groups = useMemo(() => groupByDay(jobs, new Date(today)), [jobs, today]);

  return (
    <div className="days">
      {groups.map((group) => (
        <section className="day" key={group.key} aria-label={`${group.label} 기록`}>
          <h3 className="day-head">
            <span>{group.label}</span>
            <span className="muted">{group.jobs.length}장</span>
          </h3>
          {/* 격자: 최신이 왼쪽 위, 왼쪽 → 오른쪽, 위 → 아래 순서. 썸네일은 같은 비율로 잘라 칸을 맞춘다. */}
          <ul className="grid">
            {group.jobs.map((job) => (
              <Card key={job.id} job={job} now={now} progress={progress[job.id]} onSelect={onSelect} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Card({
  job,
  now,
  progress,
  onSelect,
}: {
  job: Job;
  now: number;
  progress: Progress | undefined;
  onSelect: (id: string) => void;
}) {
  const src = api.imageUrl(job);
  const created = new Date(job.created_at);
  const elapsed = Math.max(0, Math.round((now - created.getTime()) / 1000));
  const p = job.status === "generating" ? progress : undefined;
  const tags = displayTags(job);

  return (
    <li>
      <button className={`card ${job.status}`} onClick={() => onSelect(job.id)}>
        <div className="thumb">
          {src ? (
            <img src={src} alt={caption(job)} loading="lazy" />
          ) : (
            <div className="placeholder">
              <strong>{STATUS_LABEL[job.status]}</strong>
              {p && (
                <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={p.total} aria-valuenow={p.step}>
                  <span style={{ width: `${(p.step / p.total) * 100}%` }} />
                </div>
              )}
              {isActive(job) && (
                <span>
                  {p ? `${p.step}/${p.total} 스텝 · ` : ""}
                  {elapsed}초
                </span>
              )}
            </div>
          )}
        </div>
        {tags.length > 0 ? (
          <span className="card-tags" title={tags.join(", ")}>
            {tags.map((tag, i) => (
              <span className="tag" key={`${i}-${tag}`}>
                {tag}
              </span>
            ))}
          </span>
        ) : (
          // 한국어 요청이 아직 태그로 바뀌기 전에는 요청 문장을 잠깐 보여 준다.
          <span className="caption pending">{caption(job)}</span>
        )}
      </button>
    </li>
  );
}
