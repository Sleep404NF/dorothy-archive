import { useCallback, useEffect, useRef, useState } from "react";
import { api, isActive, subscribeEvents, type Job, type JobInput, type Preset, type Progress } from "./api";
import { Composer } from "./Composer";
import { Gallery } from "./Gallery";
import { JobDetail } from "./JobDetail";
import { PresetManager } from "./PresetManager";

const PAGE_SIZE = 24;

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [live, setLive] = useState(false);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;
  const [managing, setManaging] = useState(false);

  const refreshPresets = useCallback(async () => {
    try {
      setPresets(await api.listPresets());
    } catch {
      // 기록 목록 쪽 배너가 연결 오류를 이미 보여 준다.
    }
  }, []);

  useEffect(() => {
    void refreshPresets();
  }, [refreshPresets]);

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

  // 실시간 이벤트(SSE): 상태가 바뀐 작업은 목록에서 바로 바꾸고, 진행률은 따로 모아 둔다.
  useEffect(
    () =>
      subscribeEvents({
        onJob: (job) => {
          if (jobsRef.current.some((j) => j.id === job.id)) {
            setJobs((prev) => prev.map((j) => (j.id === job.id ? job : j)));
          } else {
            void refresh(); // 새 작업이면 목록 순서와 개수를 다시 받아 온다.
          }
          if (!isActive(job)) {
            setProgress((prev) => {
              const { [job.id]: _done, ...rest } = prev;
              return rest;
            });
          }
        },
        onProgress: (id, p) => setProgress((prev) => ({ ...prev, [id]: p })),
        onConnection: (open) => {
          setLive(open);
          if (open) void refresh(); // 끊겼던 사이에 놓친 변화를 맞춘다.
        },
      }),
    [refresh],
  );

  // 실시간 연결이 안 될 때만, 진행 중인 작업이 있으면 2초마다 확인한다.
  const anyActive = jobs.some(isActive);
  useEffect(() => {
    if (live || !anyActive) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [live, anyActive, refresh]);

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
          <Composer presets={presets} onSubmit={submit} onManagePresets={() => setManaging(true)} />
        </aside>

        <section className="archive" aria-label="생성 기록">
          <div className="archive-head">
            <h2>기록</h2>
            {loaded && !error && <span className="muted">{total}장</span>}
            <span className={`live ${live ? "on" : ""}`} title={live ? "실시간 연결됨" : "실시간 연결 끊김 (2초마다 확인)"}>
              {live ? "실시간" : "연결 중…"}
            </span>
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

          <Gallery jobs={jobs} progress={progress} onSelect={setSelectedId} />

          {jobs.length < total && (
            <button className="ghost more" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
              더 보기 ({total - jobs.length}장 남음)
            </button>
          )}
        </section>
      </main>

      {selected && <JobDetail job={selected} onClose={() => setSelectedId(null)} onRerun={rerun} />}
      {managing && (
        <PresetManager presets={presets} onChanged={refreshPresets} onClose={() => setManaging(false)} />
      )}
    </div>
  );
}
