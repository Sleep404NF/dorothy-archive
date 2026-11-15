import { useEffect, useRef, useState } from "react";
import { api, PRESET_TYPE_LABEL, splitTags, type Preset, type PresetInput, type PresetType } from "./api";

const TYPES: PresetType[] = ["character", "style"];

interface Draft {
  id: string | null; // null 이면 새 프리셋
  type: PresetType;
  name: string;
  positive: string;
  negative: string;
}

const emptyDraft = (type: PresetType = "character"): Draft => ({
  id: null,
  type,
  name: "",
  positive: "",
  negative: "",
});

const toDraft = (p: Preset): Draft => ({
  id: p.id,
  type: p.type,
  name: p.name,
  positive: p.positive.join(", "),
  negative: p.negative.join(", "),
});

interface Props {
  presets: Preset[];
  onChanged: () => Promise<void>;
  onClose: () => void;
}

export function PresetManager({ presets, onChanged, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<Draft>(() => (presets[0] ? toDraft(presets[0]) : emptyDraft()));
  const [importing, setImporting] = useState(false);
  const [json, setJson] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const el = dialog.current;
    if (el && !el.open) el.showModal();
  }, []);

  const run = async (task: () => Promise<string>) => {
    setBusy(true);
    setMessage(null);
    try {
      const text = await task();
      await onChanged();
      setMessage({ kind: "ok", text });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const input = (): PresetInput => ({
    type: draft.type,
    name: draft.name.trim(),
    positive: splitTags(draft.positive),
    negative: splitTags(draft.negative),
  });

  const save = () =>
    run(async () => {
      const saved = draft.id ? await api.updatePreset(draft.id, input()) : await api.createPreset(input());
      setDraft(toDraft(saved));
      return draft.id ? "저장했습니다." : "새 프리셋을 만들었습니다.";
    });

  const remove = () => {
    if (!draft.id || !confirm(`'${draft.name}' 프리셋을 지울까요? 이미 만든 기록에는 영향이 없습니다.`)) return;
    const id = draft.id;
    void run(async () => {
      await api.deletePreset(id);
      setDraft(emptyDraft(draft.type));
      return "지웠습니다.";
    });
  };

  const importJson = () =>
    run(async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(json);
      } catch {
        throw new Error("JSON 형식이 올바르지 않습니다.");
      }
      const items = (Array.isArray(parsed) ? parsed : [parsed]) as PresetInput[];
      let done = 0;
      for (const item of items) {
        try {
          await api.createPreset({ ...item, negative: item.negative ?? [] });
          done += 1;
        } catch (e) {
          const name = item?.name ?? `${done + 1}번째`;
          throw new Error(`${done}개 가져온 뒤 '${name}'에서 멈췄습니다: ${e instanceof Error ? e.message : e}`);
        }
      }
      setJson("");
      setImporting(false);
      return `${done}개를 가져왔습니다.`;
    });

  const canSave = draft.name.trim() !== "" && splitTags(draft.positive).length > 0 && !busy;

  return (
    <dialog
      ref={dialog}
      className="detail presets-dialog"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialog.current) dialog.current?.close();
      }}
    >
      <div className="manager">
        <nav className="manager-list" aria-label="프리셋 목록">
          {TYPES.map((type) => (
            <section key={type}>
              <h3>{PRESET_TYPE_LABEL[type]}</h3>
              <ul>
                {presets
                  .filter((p) => p.type === type)
                  .map((p) => (
                    <li key={p.id}>
                      <button
                        className="item"
                        aria-current={!importing && draft.id === p.id}
                        onClick={() => {
                          setImporting(false);
                          setMessage(null);
                          setDraft(toDraft(p));
                        }}
                      >
                        {p.name}
                      </button>
                    </li>
                  ))}
              </ul>
            </section>
          ))}
          <div className="manager-new">
            <button
              className="ghost"
              onClick={() => {
                setImporting(false);
                setMessage(null);
                setDraft(emptyDraft(draft.type));
              }}
            >
              + 새 프리셋
            </button>
            <button
              className="ghost"
              onClick={() => {
                setMessage(null);
                setImporting(true);
              }}
            >
              JSON 가져오기
            </button>
          </div>
        </nav>

        <div className="manager-edit">
          <div className="detail-top">
            <h2>{importing ? "JSON 가져오기" : draft.id ? "프리셋 수정" : "새 프리셋"}</h2>
            <button className="ghost" onClick={() => dialog.current?.close()}>
              닫기
            </button>
          </div>

          {importing ? (
            <>
              <label className="field">
                <span>프리셋 객체 하나 또는 배열</span>
                <textarea
                  rows={12}
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                  spellCheck={false}
                  className="mono"
                  placeholder={`[\n  {\n    "type": "character",\n    "name": "은발 소녀",\n    "positive": ["1girl", "silver hair", "long hair"],\n    "negative": ["short hair"]\n  }\n]`}
                />
              </label>
              <button className="primary" disabled={busy || json.trim() === ""} onClick={() => void importJson()}>
                가져오기
              </button>
            </>
          ) : (
            <>
              <fieldset className="field">
                <legend>종류</legend>
                <div className="segmented">
                  {TYPES.map((type) => (
                    <button
                      type="button"
                      key={type}
                      aria-pressed={draft.type === type}
                      onClick={() => setDraft({ ...draft, type })}
                    >
                      {PRESET_TYPE_LABEL[type]}
                    </button>
                  ))}
                </div>
              </fieldset>

              <label className="field">
                <span>이름</span>
                <input
                  type="text"
                  value={draft.name}
                  maxLength={50}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder={draft.type === "character" ? "예: 은발 소녀" : "예: 수채화"}
                />
              </label>

              <label className="field">
                <span>태그 (쉼표로 구분)</span>
                <textarea
                  rows={5}
                  className="mono"
                  value={draft.positive}
                  onChange={(e) => setDraft({ ...draft, positive: e.target.value })}
                  placeholder={
                    draft.type === "character"
                      ? "1girl, solo, silver hair, long hair, blue eyes, (hair ribbon:1.1)"
                      : "masterpiece, best quality, watercolor (medium), soft lighting"
                  }
                />
              </label>

              <label className="field">
                <span>제외 태그 (쉼표로 구분)</span>
                <textarea
                  rows={2}
                  className="mono"
                  value={draft.negative}
                  onChange={(e) => setDraft({ ...draft, negative: e.target.value })}
                  placeholder="short hair"
                />
              </label>
              <p className="hint">제외 태그는 제외 프롬프트에 들어가고, 요청에서 같은 태그가 나와도 빠집니다.</p>

              <div className="actions">
                <button className="primary" disabled={!canSave} onClick={() => void save()}>
                  {draft.id ? "저장" : "만들기"}
                </button>
                {draft.id && (
                  <button className="ghost danger" disabled={busy} onClick={remove}>
                    삭제
                  </button>
                )}
              </div>
            </>
          )}

          {message && (
            <p className={message.kind === "error" ? "form-error" : "form-ok"} role="status">
              {message.text}
            </p>
          )}
        </div>
      </div>
    </dialog>
  );
}
