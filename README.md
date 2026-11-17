<div align="center">

# 🌙 Project: DOROTHY

### Dream Archive

**키워드로 꿈을 그리고, 기록하고, 다시 꺼내 보는 곳.**

한국어 요청을 Danbooru 태그로 바꿔 애니풍 일러스트를 생성하고,<br>
생성 기록과 시드를 보관해 언제든 같은 그림을 다시 꺼낼 수 있는 로컬 AI 이미지 도구

![status](https://img.shields.io/badge/status-WIP-8b5cf6)
![name](https://img.shields.io/badge/name-working%20title-6366f1)
![python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![react](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![comfyui](https://img.shields.io/badge/ComfyUI-SDXL-1f2937)
![ollama](https://img.shields.io/badge/Ollama-gemma3:4b-000000)

</div>

---

## ✨ 동작 방식

<table>
<tr>
<td width="42%"><img src="docs/images/moonlit-lake.jpg" alt="달빛 아래 호숫가에 앉아 있는 소녀"></td>
<td>

**① 한국어로 요청**
```
달빛 아래 호숫가에 앉아 있는 여우 귀 소녀
```

**② 로컬 LLM이 Danbooru 태그로 변환** · 6.4s
```
1girl, solo, long hair, red eyes, elf ears,
white dress, sitting, looking at moon,
full body, lake, night, moonlight, reflection
```

> 처음에는 "여우 귀"가 `elf ears`로 잘못 변환됐다.<br>
> 지금은 한국어 용어집 + 태그 사전 검증으로 `fox ears`로 바로잡는다. (아래 *태그 검증* 참고)

**③ SDXL로 생성** · 90.6s
`832×1216` · `28 steps` · `CFG 5.5` · `seed 3361504414`

**④ 기록에 보관**
요청, 태그, 시드, 파라미터를 함께 저장해서<br>
같은 시드로 다시 만들거나 시드만 바꿔 변주할 수 있다.

</td>
</tr>
</table>

> 측정 환경: MacBook Pro M3 Pro / 18GB · ComfyUI(MPS) · NoobAI-XL v1.1 · gemma3:4b

---

## 🎯 주요 기능

| 기능 | 설명 |
|---|---|
| **한국어 → 태그 변환** | Ollama 로컬 LLM이 자연어 요청을 Danbooru 태그 프롬프트로 변환한다 |
| **키워드 프리셋 조합** | 캐릭터·스타일 프리셋(JSON)을 `캐릭터 → 요청 태그 → 스타일` 순서로 결정적으로 병합한다. 중복 제거, 품질 태그 앞으로 정렬, 프리셋 제외 태그와 충돌하는 태그 제거 |
| **태그 검증** | Danbooru 태그 사전(약 5.7만 개)으로 별칭을 대표 태그로 정리하고 없는 태그는 뺀다. 한국어 용어집으로 LLM에 힌트를 주고 정답 태그를 넣는다. 바뀐 내용은 기록에 보고서로 남긴다 |
| **태그 직접 입력** | 완성된 프롬프트를 넣으면 LLM 단계를 건너뛴다 |
| **작업 큐 + 실시간 진행률** | 작업 id 만 큐에 넣고 워커가 실행한다. `inline`(API 안에서 실행, Redis 불필요)과 `celery`(Redis + 별도 워커) 두 모드를 설정으로 고른다. 생성 스텝 진행률은 SSE 로 카드의 진행 바에 실시간 표시 |
| **저장소 교체** | DB 는 SQLite ↔ PostgreSQL(JSONB), 이미지는 로컬 폴더 ↔ S3 호환 스토리지(RustFS, R2, B2 등)를 설정으로 바꾼다. 기존 데이터를 옮기는 스크립트 포함 |
| **비동기 생성 작업** | 요청하면 바로 `202 Accepted`와 작업 ID를 돌려주고, 생성은 백그라운드에서 진행한다 |
| **생성 기록 아카이브** | 요청·태그·시드·파라미터·소요 시간을 함께 저장하고 최신순으로 보여준다 |
| **시드 재생성** | 저장된 프롬프트로 같은 시드 재생성, 또는 시드만 바꾼 변주 |
| **WebP 저장** | ComfyUI가 돌려준 PNG를 WebP(품질 90)로 바꿔 저장한다. 실제 생성 기록 30장 기준 33.3MB → 2.9MB |
| **NSFW 제외 옵션** | 요청마다 제외 프롬프트에 `nsfw` 태그를 붙일지 선택 |
| **React 웹 UI** | 요청 입력, 기록 갤러리, 상세 보기(분류별 태그, 프롬프트 복사, 재생성) |

---

## 🏗️ 구조

```mermaid
flowchart LR
    UI["React UI"] -->|"POST /jobs"| API["FastAPI"]
    API -->|"202 + job id"| UI
    API -->|"job id"| Q[("Redis<br/>Celery 브로커")]
    Q --> W["Celery 워커<br/>(solo, 동시성 1)"]
    W --> P["Pipeline"]
    P -.->|"상태·진행률<br/>Pub/Sub"| Q
    API -.->|"SSE /events"| UI
    P -->|"한국어 요청"| LLM["Ollama<br/>gemma3:4b"]
    LLM -->|"Danbooru 태그"| P
    P -->|"GenerationParams"| IB{{"ImageBackend<br/>인터페이스"}}
    IB --> CU["ComfyUI<br/>NoobAI-XL"]
    CU -.->|"WebSocket 진행률"| IB
    IB -.->|"예정"| NAI["NovelAI"]
    IB -.->|"예정"| GPU["원격 GPU 서버"]
    P --> DB[("PostgreSQL<br/>(또는 SQLite)")]
    P --> IMG[("S3 호환 · RustFS<br/>(또는 로컬 폴더)")]
```

`inline` 모드에서는 Redis 와 워커 없이 API 프로세스 안에서 같은 Pipeline 이 돌고, 이벤트는 메모리 버스로 전달된다.
아무 설정도 하지 않으면 **SQLite + 로컬 폴더 + inline 큐**로 Docker 없이 돌고, `.env` 만 바꾸면 **PostgreSQL + S3 호환 스토리지 + Celery** 로 바뀐다.

### 설계 포인트

**1. 이미지 백엔드 추상화**
파이프라인은 `ImageBackend` 인터페이스(`generate`, `health`, `release`)만 안다. 지금은 로컬 ComfyUI를 쓰지만, NovelAI나 원격 GPU 서버로 바꾸려면 구현체 하나를 추가해서 등록만 하면 된다. 파이프라인 코드는 바뀌지 않는다.

**2. 18GB 통합 메모리 안에서 LLM과 SDXL 나눠 쓰기**
맥 한 대에서 LLM과 SDXL을 동시에 올리면 메모리가 부족하다. 그래서 메모리 규칙을 파이프라인에 넣었다.
- 작업은 `asyncio.Lock`으로 **한 번에 하나씩만** 처리
- LLM은 `keep_alive=0`으로 호출해서 **응답 직후 바로 내림**
- SDXL은 연속 생성 시 재로딩을 피하려고 **올려둔 채로 두고**, 다음에 LLM이 필요할 때 내림
- 백엔드가 `uses_local_memory = False`(원격)이면 이 규칙을 건너뛰고 LLM을 계속 올려둠

**3. 재현 가능한 기록**
기록에는 프리셋 참조가 아니라 **생성 당시의 최종 프롬프트와 파라미터 전체**를 저장한다. 그래서 나중에도 같은 시드로 같은 그림을 다시 만들 수 있다.

**4. LLM 태그 검증 (사전 + 용어집)**
작은 LLM은 없는 태그를 지어내거나(`drinking coffee`), 있는 태그지만 뜻이 다른 것을 고른다(`여우 귀` → `elf ears`). 앞의 것은 태그 사전으로, 뒤의 것은 한국어 용어집으로 잡는다.
- 사전: 별칭은 대표 태그로 바꾸고(`maid outfit` → `maid`), 사전에 없는 태그는 빼고 기록한다
- 용어집: 요청에 `여우 귀`가 있으면 LLM에 `fox ears`를 힌트로 주고, 결과에 반드시 넣고, `pointy ears`처럼 틀린 태그는 뺀다
- 무엇이 바뀌었는지는 작업 기록의 `tag_report`에 남아 상세 보기에서 확인할 수 있다

**5. 작업 큐와 실시간 진행률 (inline / celery 두 모드)**
- 큐에는 작업 전체가 아니라 **id 만** 넣는다. 작업 내용은 먼저 DB 에 저장하고, 실행하는 쪽이 DB 에서 꺼내 읽는다. 같은 작업이 두 번 배달돼도 `queued` 상태일 때만 실행해서 한 번만 그린다
- `JobQueue`(InlineQueue / CeleryQueue)와 `EventBus`(InMemoryBus / RedisBus)를 인터페이스로 나눠서, 같은 Pipeline 코드가 두 모드에서 그대로 돈다
- 워커는 `--pool=solo --concurrency=1` 로 띄운다. GPU 는 한 번에 한 장만 그려야 하고, LLM 과 SDXL 을 번갈아 올리는 메모리 규칙도 한 프로세스 안에서 지켜진다
- 진행률은 ComfyUI 웹소켓의 `progress` 메시지를 받아 이벤트로 보내고, API 가 SSE(`/events`)로 브라우저에 전달한다. 웹소켓이 끊기면 진행률 없이 `/history` 폴링으로 끝까지 기다린다
- Redis 가 꺼져 있으면 오래 기다리지 않고 바로 `503` 을 돌려주고 작업은 실패로 기록한다
- 이벤트는 놓쳐도 되는 알림이고 상태의 기준은 DB 다. 브라우저는 SSE 가 끊기면 2초 폴링으로 돌아가고, 다시 연결되면 목록을 맞춘다

**6. 저장소 추상화 (DB / 이미지)**
- DB 는 SQLAlchemy Core 로 테이블을 정의해서 **같은 코드가 SQLite 와 PostgreSQL 에서** 돈다. 작업은 목록 조회에 쓰는 값(id, 생성 시각, 상태)만 컬럼으로 두고 나머지는 `data` 한 칸에 넣는데, PostgreSQL 에서는 이 칸이 `JSONB` 다
- 이미지는 `ImageStorage`(LocalStorage / S3Storage) 인터페이스 뒤에 둔다. DB 에는 `/images/{작업 id}.webp` 만 저장해서, 저장소를 바꿔도 기록은 그대로다. 로컬 개발은 Docker 의 RustFS, 나중에는 엔드포인트만 바꿔 Cloudflare R2 나 Backblaze B2 로 옮길 수 있다. 처음엔 MinIO 를 썼는데 공식 Docker 이미지가 내려가서 RustFS 로 바꿨고, 앱 코드는 S3 API 만 쓰기 때문에 한 줄도 바뀌지 않았다
- 이미지 이름은 작업마다 고유하고 바뀌지 않아서 `Cache-Control: immutable` 로 내려준다
- `scripts/migrate_storage.py` 로 SQLite + 로컬 폴더의 기존 데이터를 옮긴다. 여러 번 돌려도 중복되지 않는다

**7. 중단된 작업 정리**
서버가 생성 도중에 꺼지면, 다시 켤 때 끝나지 않은 작업을 `failed`로 정리해서 기록이 `generating` 상태로 남지 않게 한다. celery 모드에서는 API 를 재시작해도 대기 중인 작업은 브로커에 남아 있으므로 건드리지 않고, 워커가 시작할 때 실행 중이던 작업만 정리한다.

---

## 🔌 API

| Method | Endpoint | 설명 |
|---|---|---|
| `GET` | `/health` | 이미지 백엔드 상태 확인 |
| `POST` | `/jobs` | 생성 작업 등록 (`request` 또는 `prompt` 중 하나) |
| `GET` | `/jobs` | 생성 기록 목록 (`limit`, `offset`, `status`) |
| `GET` | `/jobs/{id}` | 작업 상세 / 진행 상태 |
| `POST` | `/jobs/{id}/rerun` | 같은 시드로 재생성 (`new_seed=true`면 변주) |
| `GET` | `/images/{name}` | 생성된 이미지 |
| `POST` | `/tags` | 생성 없이 태그 변환만 |
| `GET` `POST` | `/presets` | 프리셋 목록(`type`으로 필터) / 생성 |
| `GET` `PUT` `DELETE` | `/presets/{id}` | 프리셋 조회 / 수정 / 삭제 |
| `POST` | `/presets/compose` | 생성 없이 프리셋 병합 결과만 미리 보기 |
| `GET` | `/events` | 작업 상태 변화와 생성 진행률 (Server-Sent Events) |
| `POST` | `/release` | 로드된 모델을 메모리에서 내리기 |

<details>
<summary><b>요청 예시</b></summary>

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"request": "달빛 아래 호숫가에 앉아 있는 소녀", "seed": 42}'
```

```json
{
  "id": "a1b2c3d4e5f6",
  "status": "queued",
  "seed": 42,
  "width": 832,
  "height": 1216,
  "steps": 28,
  "cfg": 5.5,
  "backend": "comfyui"
}
```

</details>

---

## 🚀 실행하기

### 준비물
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) + SDXL 애니 모델 (`NoobAI-XL-v1.1.safetensors`)
- [Ollama](https://ollama.com) + `gemma3:4b`
- Python 3.12, Node.js

### 실행

```bash
# 1. 모델 준비
ollama pull gemma3:4b

# 2. 백엔드 (ComfyUI가 127.0.0.1:8188 에서 실행 중이어야 한다)
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. 프론트엔드
cd frontend && npm install && npm run dev
```

위 방법은 기본 구성(SQLite + 로컬 폴더 + inline 큐)이다. **PostgreSQL + S3 호환 스토리지(RustFS) + Celery** 로 돌리려면 Docker 로 인프라를 띄우고 `.env` 를 만든다.

```bash
docker compose up -d --wait              # Redis, PostgreSQL, RustFS
cp .env.example .env                     # 필요한 줄의 주석을 푼다

# 지금까지 쌓인 SQLite 기록과 outputs/ 이미지를 옮기기 (선택)
cd backend && source .venv/bin/activate
python scripts/migrate_storage.py --dry-run && python scripts/migrate_storage.py

uvicorn app.main:app --reload                                              # API
celery -A app.worker worker --pool=solo --concurrency=1 --loglevel=info    # 워커 (DOROTHY_QUEUE=celery 일 때, 다른 터미널)
```
RustFS 웹 콘솔은 `http://127.0.0.1:9001/rustfs/console/` (아이디 `dorothy`, 비밀번호 `dorothy-secret`)에서 볼 수 있다. 현재 구성은 `GET /health` 의 `queue`, `database`, `storage` 로 확인한다.

### 테스트

```bash
cd backend && pytest
# PostgreSQL 테스트까지 돌리려면 (docker compose 의 postgres 에 테스트용 DB 를 만든 뒤)
docker compose exec postgres createdb -U dorothy dorothy_test
DOROTHY_TEST_DATABASE_URL=postgresql+psycopg://dorothy:dorothy@127.0.0.1:5432/dorothy_test pytest
```

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DOROTHY_IMAGE_BACKEND` | `comfyui` | 이미지 백엔드 |
| `DOROTHY_COMFYUI_HOST` | `http://127.0.0.1:8188` | ComfyUI 주소 |
| `DOROTHY_COMFYUI_CHECKPOINT` | 워크플로 기본값 | 사용할 체크포인트 파일 |
| `DOROTHY_WORKFLOW` | `workflows/txt2img_sdxl.api.json` | ComfyUI 워크플로 |
| `DOROTHY_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 주소 |
| `DOROTHY_OLLAMA_MODEL` | `gemma3:4b` | 태그 변환 모델 |
| `DOROTHY_QUEUE` | `inline` | 작업 큐 (`inline` 또는 `celery`) |
| `DOROTHY_REDIS_URL` | `redis://127.0.0.1:6379/0` | celery 모드의 브로커와 이벤트 채널 |
| `DOROTHY_IMAGE_FORMAT` | `webp` | 생성 이미지 저장 형식 (`webp` 또는 `png`) |
| `DOROTHY_WEBP_QUALITY` | `90` | WebP 품질 |
| `DOROTHY_DATABASE_URL` | (없음 → SQLite) | 예: `postgresql+psycopg://dorothy:dorothy@127.0.0.1:5432/dorothy` |
| `DOROTHY_STORAGE` | `local` | 이미지 저장소 (`local` 또는 `s3`) |
| `DOROTHY_S3_ENDPOINT` | (없음 → AWS) | S3 호환 엔드포인트. docker compose 의 RustFS: `http://127.0.0.1:9000` |
| `DOROTHY_S3_BUCKET` | `dorothy` | 버킷 (없으면 만든다) |
| `DOROTHY_S3_ACCESS_KEY` / `DOROTHY_S3_SECRET_KEY` | | 접근 키 |
| `DOROTHY_S3_REGION` | `us-east-1` | R2 는 `auto` |
| `DOROTHY_DB` | `data/dorothy.db` | SQLite 파일 위치 (`DOROTHY_DATABASE_URL` 이 없을 때) |
| `DOROTHY_OUTPUT_DIR` | `outputs` | 로컬 이미지 폴더 (`DOROTHY_STORAGE=local` 일 때) |
| `DOROTHY_TAG_VALIDATION` | `1` | `0`이면 태그 검증을 끈다 |
| `DOROTHY_TAG_DICTIONARY` | `prompts/tags/danbooru_tags.csv.gz` | 태그 사전 |
| `DOROTHY_GLOSSARY` | `prompts/glossary.ko.json` | 한국어 용어집 |
| `DOROTHY_API` | `http://127.0.0.1:8000` | 프론트 개발 서버의 API 프록시 대상 |

---

## 🗺️ 로드맵

- [x] ComfyUI 워크플로로 한 장 생성
- [x] 한국어 요청 → Danbooru 태그 변환
- [x] 생성 기록 저장 + 시드 재생성
- [x] React UI (요청 입력, 기록 갤러리, 상세 보기)
- [x] 캐릭터 / 스타일 키워드 프리셋(JSON) 조합
- [x] 태그 사전 + 한국어 용어집으로 LLM 태그 변환 결과 검증
- [x] 작업 큐 분리 (Celery + Redis) + 실시간 진행률(SSE)
- [x] 저장소 전환 (PostgreSQL + S3 호환 스토리지)
- [ ] 로그인 (JWT)
- [ ] GitHub Actions CI
- [ ] 원격 GPU 서버 / NovelAI 백엔드
- [ ] LoRA 연결

---

## 🖼️ 갤러리

<p align="center">
  <img src="docs/images/snow-archer.jpg" width="24%">
  <img src="docs/images/moonlit-lake.jpg" width="24%">
  <img src="docs/images/reading-room.jpg" width="24%">
</p>
<p align="center">
  <img src="docs/images/sunset-sea.jpg" width="74%">
</p>

---

## 📚 데이터 출처

- 태그 사전: [DominikDoom/a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)의 `danbooru.csv` (MIT License)를 `backend/scripts/build_tag_dictionary.py`로 줄여서 사용 (작가 태그 제외, 사용 횟수 50회 이상)

---

<div align="center">

**DOROTHY** is a working title. ·
Made by [Dorothy404](https://github.com/Sleep404NF)

</div>
