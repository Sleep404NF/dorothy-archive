import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, type JobInput, type Preset, type PresetType } from "./api";

const SHAPES = [
  { id: "portrait", label: "세로", width: 832, height: 1216 },
  { id: "landscape", label: "가로", width: 1216, height: 832 },
  { id: "square", label: "정사각", width: 1024, height: 1024 },
] as const;

type Mode = "request" | "prompt";

interface Props {
  presets: Preset[];
  onSubmit: (input: JobInput) => Promise<void>;
  onManagePresets: () => void;
}

export function Composer({ presets, onSubmit, onManagePresets }: Props) {
  const [mode, setMode] = useState<Mode>("request");
  const [text, setText] = useState("");
  const [characterId, setCharacterId] = useState("");
  const [styleId, setStyleId] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [shape, setShape] = useState<(typeof SHAPES)[number]["id"]>("portrait");
  const [steps, setSteps] = useState(28);
  const [seed, setSeed] = useState("");
  const [excludeNsfw, setExcludeNsfw] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const seedValid = seed === "" || /^\d{1,10}$/.test(seed);
  const hasPreset = characterId !== "" || styleId !== "";
  const canSubmit = (text.trim() !== "" || hasPreset) && seedValid && !busy;
  const requestPending = mode === "request" && text.trim() !== "";

  // 고른 프리셋이 지워지면 선택을 푼다.
  useEffect(() => {
    if (characterId && !presets.some((p) => p.id === characterId)) setCharacterId("");
    if (styleId && !presets.some((p) => p.id === styleId)) setStyleId("");
  }, [presets, characterId, styleId]);

  // 프리셋을 고르면 합쳐질 프롬프트를 미리 보여 준다. 한국어 요청은 태그 변환 뒤에 합쳐지므로 제외.
  useEffect(() => {
    if (!hasPreset || requestPending) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      api
        .composePresets({
          character_preset_id: characterId || undefined,
          style_preset_id: styleId || undefined,
          prompt: mode === "prompt" ? text : undefined,
        })
        .then((c) => setPreview(c.positive))
        .catch(() => setPreview(null));
    }, 300);
    return () => clearTimeout(timer);
  }, [hasPreset, requestPending, characterId, styleId, mode, text]);

  const submit = async () => {
    if (!canSubmit) return;
    const { width, height } = SHAPES.find((s) => s.id === shape)!;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        ...(text.trim() ? { [mode]: text.trim() } : {}),
        character_preset_id: characterId || undefined,
        style_preset_id: styleId || undefined,
        exclude_nsfw: excludeNsfw,
        seed: seed === "" ? undefined : Number(seed),
        width,
        height,
        steps,
      });
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
  };

  return (
    <form
      className="composer"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="segmented" role="tablist" aria-label="입력 방식">
        <button type="button" role="tab" aria-selected={mode === "request"} onClick={() => setMode("request")}>
          한국어로 요청
        </button>
        <button type="button" role="tab" aria-selected={mode === "prompt"} onClick={() => setMode("prompt")}>
          태그 직접 입력
        </button>
      </div>

      <label className="field">
        <span className="sr-only">{mode === "request" ? "그리고 싶은 장면" : "Danbooru 태그"}</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={5}
          placeholder={
            mode === "request"
              ? "예: 비 오는 밤 도시에서 우산을 쓴 검은 단발 소녀"
              : "예: 1girl, solo, black hair, bob cut, holding umbrella, city, night, rain"
          }
        />
      </label>
      <p className="hint">
        {mode === "request"
          ? "로컬 LLM이 Danbooru 태그로 바꾼 뒤 그립니다."
          : "LLM을 거치지 않고 입력한 태그 그대로 그립니다."}
      </p>

      <fieldset className="field presets">
        <legend>
          프리셋
          <button type="button" className="link" onClick={onManagePresets}>
            관리
          </button>
        </legend>
        <PresetSelect type="character" presets={presets} value={characterId} onChange={setCharacterId} />
        <PresetSelect type="style" presets={presets} value={styleId} onChange={setStyleId} />
        {hasPreset && (
          <p className="hint">
            {requestPending
              ? "요청을 태그로 바꾼 뒤 캐릭터 → 요청 → 스타일 순서로 합칩니다."
              : preview
                ? <span className="preview">{preview}</span>
                : "캐릭터 → 입력 태그 → 스타일 순서로 합칩니다."}
          </p>
        )}
      </fieldset>

      <fieldset className="field">
        <legend>비율</legend>
        <div className="segmented">
          {SHAPES.map((s) => (
            <button type="button" key={s.id} aria-pressed={shape === s.id} onClick={() => setShape(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
      </fieldset>

      <label className="field">
        <span>
          스텝 <b>{steps}</b>
        </span>
        <input type="range" min={8} max={40} value={steps} onChange={(e) => setSteps(Number(e.target.value))} />
      </label>

      <label className="field">
        <span>시드</span>
        <input
          type="text"
          inputMode="numeric"
          value={seed}
          onChange={(e) => setSeed(e.target.value.trim())}
          placeholder="비워 두면 무작위"
          aria-invalid={!seedValid}
        />
      </label>

      <label className="check">
        <input type="checkbox" checked={excludeNsfw} onChange={(e) => setExcludeNsfw(e.target.checked)} />
        <span>제외 프롬프트에 nsfw 넣기</span>
      </label>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button className="primary" type="submit" disabled={!canSubmit}>
        {busy ? "보내는 중…" : "그리기"}
      </button>
      <p className="hint center">⌘/Ctrl + Enter 로도 보낼 수 있습니다.</p>
    </form>
  );
}

function PresetSelect({
  type,
  presets,
  value,
  onChange,
}: {
  type: PresetType;
  presets: Preset[];
  value: string;
  onChange: (id: string) => void;
}) {
  const options = presets.filter((p) => p.type === type);
  const label = type === "character" ? "캐릭터" : "스타일";
  return (
    <label className="preset-row">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">없음</option>
        {options.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}
