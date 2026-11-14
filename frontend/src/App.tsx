import { useCallback, useEffect, useState } from "react";
import { api, isActive, type Job, type JobInput } from "./api";
import { Composer } from "./Composer";
import { Gallery } from "./Gallery";
import { JobDetail } from "./JobDetail";

const PAGE_SIZE = 24;

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await api.listJobs(limit);
      setJobs(page.items);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoaded(true);
    }
  }, [limit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 진행 중인 작업이 있을 때만 자주 확인한다.
  const anyActive = jobs.some(isActive);
  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [anyActive, refresh]);

  const submit = async (input: JobInput) => {
    await api.createJob(input);
    await refresh();
  };

  const rerun = async (job: Job, newSeed: boolean) => {
    const created = await api.rerun(job.id, newSeed);
    await refresh();
    setSelectedId(created.id);
  };

  const selected = jobs.find((j) => j.id === selectedId) ?? null;

  return (
    <div className="app">
      <header className="masthead">
        <h1>DOROTHY</h1>
        <p>Dream Archive — 키워드로 꿈을 그리고, 기록하고, 다시 꺼내 보는 곳</p>
      </header>

      <main className="layout">
        <aside className="sidebar">
          <Composer onSubmit={submit} />
        </aside>

        <section className="archive" aria-label="생성 기록">
          <div className="archive-head">
            <h2>기록</h2>
            {loaded && !error && <span className="muted">{total}장</span>}
          </div>

          {error && (
            <div className="banner" role="alert">
              <span>{error}</span>
              <button className="ghost" onClick={() => void refresh()}>
                다시 시도
              </button>
            </div>
          )}

          {loaded && !error && jobs.length === 0 && (
            <p className="empty">아직 기록이 없습니다. 왼쪽에 그리고 싶은 장면을 적어 보세요.</p>
          )}

          <Gallery jobs={jobs} onSelect={setSelectedId} />

          {jobs.length < total && (
            <button className="ghost more" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
              더 보기 ({total - jobs.length}장 남음)
            </button>
          )}
        </section>
      </main>

      {selected && <JobDetail job={selected} onClose={() => setSelectedId(null)} onRerun={rerun} />}
    </div>
  );
}
