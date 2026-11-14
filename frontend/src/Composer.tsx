import { useState, type FormEvent, type KeyboardEvent } from "react";
import type { JobInput } from "./api";

const SHAPES = [
  { id: "portrait", label: "세로", width: 832, height: 1216 },
  { id: "landscape", label: "가로", width: 1216, height: 832 },
  { id: "square", label: "정사각", width: 1024, height: 1024 },
] as const;

type Mode = "request" | "prompt";

export function Composer({ onSubmit }: { onSubmit: (input: JobInput) => Promise<void> }) {
  const [mode, setMode] = useState<Mode>("request");
  const [text, setText] = useState("");
  const [shape, setShape] = useState<(typeof SHAPES)[number]["id"]>("portrait");
  const [steps, setSteps] = useState(28);
  const [seed, setSeed] = useState("");
  const [excludeNsfw, setExcludeNsfw] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const seedValid = seed === "" || /^\d{1,10}$/.test(seed);
  const canSubmit = text.trim() !== "" && seedValid && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    const { width, height } = SHAPES.find((s) => s.id === shape)!;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        [mode]: text.trim(),
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
