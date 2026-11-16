import { useEffect, useState } from "react";
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

interface Props {
  jobs: Job[];
  progress: Record<string, Progress>;
  onSelect: (id: string) => void;
}

export function Gallery({ jobs, progress, onSelect }: Props) {
  const now = useNow(jobs.some(isActive));

  return (
    <ul className="grid">
      {jobs.map((job) => {
        const src = api.imageUrl(job);
        const elapsed = Math.max(0, Math.round((now - Date.parse(job.created_at)) / 1000));
        const p = job.status === "generating" ? progress[job.id] : undefined;
        return (
          <li key={job.id}>
            <button className={`card ${job.status}`} onClick={() => onSelect(job.id)}>
              <div className="thumb" style={{ aspectRatio: `${job.width} / ${job.height}` }}>
                {src ? (
                  <img src={src} alt={caption(job)} loading="lazy" />
                ) : (
                  <div className="placeholder">
                    <strong>{STATUS_LABEL[job.status]}</strong>
                    {p && (
                      <div
                        className="progress"
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={p.total}
                        aria-valuenow={p.step}
                      >
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
              <span className="caption">{caption(job)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
