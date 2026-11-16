import { useEffect, useRef, useState } from "react";
import { api, isActive, PRESET_TYPE_LABEL, STATUS_LABEL, type Job, type PresetType, type TagReport } from "./api";
import { caption } from "./Gallery";

const TAG_GROUPS: [string, string][] = [
  ["subject", "대상"],
  ["character", "캐릭터"],
  ["appearance", "외형"],
  ["clothing", "의상"],
  ["pose_expression", "포즈·표정"],
  ["composition", "구도"],
  ["background", "배경"],
];

interface Props {
  job: Job;
  onClose: () => void;
  onRerun: (job: Job, newSeed: boolean) => Promise<void>;
}

export function JobDetail({ job, onClose, onRerun }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const el = dialog.current;
    if (el && !el.open) el.showModal();
  }, []);

  useEffect(() => {
    setError(null);
    setCopied(false);
  }, [job.id]);

  const rerun = async (newSeed: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onRerun(job, newSeed);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!job.positive) return;
    await navigator.clipboard.writeText(job.positive);
    setCopied(true);
  };

  const src = api.imageUrl(job);
  const groups = TAG_GROUPS.filter(([key]) => job.tags?.[key]?.length);

  return (
    <dialog
      ref={dialog}
      className="detail"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialog.current) dialog.current?.close();
      }}
    >
      <div className="detail-body">
        <div className="detail-image">
          {src ? (
            <img src={src} alt={caption(job)} />
          ) : (
            <div className={`placeholder ${job.status}`} style={{ aspectRatio: `${job.width} / ${job.height}` }}>
              <strong>{STATUS_LABEL[job.status]}</strong>
            </div>
          )}
        </div>

        <div className="detail-info">
          <div className="detail-top">
            <span className={`badge ${job.status}`}>{STATUS_LABEL[job.status]}</span>
            <button className="ghost" onClick={() => dialog.current?.close()} aria-label="닫기">
              닫기
            </button>
          </div>

          {job.request && <p className="request">{job.request}</p>}
          {job.presets && Object.keys(job.presets).length > 0 && (
            <div className="used-presets">
              {(["character", "style"] as PresetType[]).map((type) => {
                const preset = job.presets?.[type];
                return preset ? (
                  <span className="chip preset" key={type} title={preset.positive.join(", ")}>
                    {PRESET_TYPE_LABEL[type]} · {preset.name}
                  </span>
                ) : null;
              })}
            </div>
          )}
          {job.error && (
            <p className="form-error" role="alert">
              {job.error}
            </p>
          )}

          {groups.length > 0 && (
            <dl className="tags">
              {groups.map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>
                    {job.tags![key].map((tag) => (
                      <span className="chip" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {job.tag_report && <TagReportView report={job.tag_report} />}

          {job.positive && (
            <div className="prompt">
              <div className="prompt-head">
                <h3>프롬프트</h3>
                <button className="ghost" onClick={() => void copy()}>
                  {copied ? "복사됨" : "복사"}
                </button>
              </div>
              <p>{job.positive}</p>
              <h3>제외 프롬프트</h3>
              <p>{job.negative}</p>
            </div>
          )}

          <dl className="meta">
            <div>
              <dt>시드</dt>
              <dd>{job.seed}</dd>
            </div>
            <div>
              <dt>크기</dt>
              <dd>
                {job.width}×{job.height}
              </dd>
            </div>
            <div>
              <dt>스텝 / CFG</dt>
              <dd>
                {job.steps} / {job.cfg}
              </dd>
            </div>
            <div>
              <dt>소요</dt>
              <dd>
                {job.generation_seconds != null
                  ? `${Math.round((job.tagging_seconds ?? 0) + job.generation_seconds)}초`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>생성</dt>
              <dd>{new Date(job.created_at).toLocaleString("ko-KR")}</dd>
            </div>
            <div>
              <dt>백엔드</dt>
              <dd>{job.backend}</dd>
            </div>
          </dl>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <div className="actions">
            <button className="primary" disabled={busy || !job.positive || isActive(job)} onClick={() => void rerun(true)}>
              시드만 바꿔 다시 그리기
            </button>
            <button className="ghost" disabled={busy || !job.positive || isActive(job)} onClick={() => void rerun(false)}>
              같은 시드로 다시
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

function TagReportView({ report }: { report: TagReport }) {
  return (
    <details className="tag-report">
      <summary>
        태그 검증
        <span className="muted">
          {[
            report.glossary?.length && `용어집 ${report.glossary.length}`,
            report.aliased?.length && `정리 ${report.aliased.length}`,
            report.dropped?.length && `제외 ${report.dropped.length}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </summary>

      {report.glossary?.map((g) => (
        <div className="report-row" key={g.term}>
          <span className="report-label">“{g.term}”</span>
          <span>
            {g.added.map((t) => (
              <span className="chip added" key={`+${t}`}>
                + {t}
              </span>
            ))}
            {g.removed.map((t) => (
              <span className="chip removed" key={`-${t}`}>
                {t}
              </span>
            ))}
          </span>
        </div>
      ))}

      {report.aliased && report.aliased.length > 0 && (
        <div className="report-row">
          <span className="report-label">표기 정리</span>
          <span>
            {report.aliased.map((a) => (
              <span className="chip" key={a.from}>
                {a.from} → {a.to}
              </span>
            ))}
          </span>
        </div>
      )}

      {report.dropped && report.dropped.length > 0 && (
        <div className="report-row">
          <span className="report-label">사전에 없어 뺌</span>
          <span>
            {report.dropped.map((t) => (
              <span className="chip removed" key={t}>
                {t}
              </span>
            ))}
          </span>
        </div>
      )}
    </details>
  );
}
