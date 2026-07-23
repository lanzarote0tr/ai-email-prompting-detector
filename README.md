# AI 프롬프팅으로 악성 이메일 탐지하기

사회공학 이메일을 사용자가 직접 분석한 뒤, AI에게 탐지 프롬프트를 작성하여 악성 이메일을 삭제하게 만드는 체험형 웹사이트입니다.

## 기능

- `emails.json`의 이메일 데이터셋 사용
- 정상/악성 정답은 실행 전 숨김
- 사용자가 메일을 하나씩 열람하며 특징 분석
- System prompt와 Detection prompt 입력 후 AI 필터 실행
- WebSocket으로 Ollama 분석 진행 상황 표시
- AI가 삭제한 이메일 기준으로 TP / FP / FN / TN 계산
- FP: 정상 이메일인데 삭제됨
- FN: 악성 이메일인데 삭제되지 않음
- SQLite 기반 리더보드 저장
- 로컬 Ollama 연동
- Ollama가 실행 중이 아니거나 AI 응답 형식이 잘못되면 실행 실패로 처리

## 실행

### Docker

```bash
cd ai_email_prompting_detector
docker build -t ai-email-prompting-detector .
docker run --rm -p 5001:5001 -v ollama-models:/root/.ollama -v email-scores:/app/data ai-email-prompting-detector
```

브라우저에서 접속:

```text
http://127.0.0.1:5001
```

이미지 빌드 시 기본 모델 `qwen3:4b`를 내려받습니다. 컨테이너 시작 시에도 모델이 없으면 다시 확인해서 내려받습니다.

더 큰 서버에서는 다음처럼 모델을 바꿔 정확도를 높일 수 있습니다.

```bash
docker run --rm -p 5001:5001 \
  -e OLLAMA_MODEL=qwen3:8b \
  -v ollama-models:/root/.ollama \
  -v email-scores:/app/data \
  ai-email-prompting-detector
```

### 로컬 Python

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen3:4b
python -m server.app
```

Ollama가 백그라운드에서 실행 중이어야 합니다. 실행되어 있지 않다면 별도 터미널에서 시작하세요.

```bash
ollama serve
```

브라우저에서 접속:

```text
http://127.0.0.1:5001
```

기본 포트는 `5001`입니다.

```bash
PORT=8000 python -m server.app
```

## 로컬 Ollama 설정

`server/config.py`에 요청한 형식으로 들어가 있습니다.

```python
OLLAMA_API = os.getenv("OLLAMA_API", "http://127.0.0.1:11434/api")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
```

환경변수로 설정해서 실행할 수 있습니다.

```bash
export OLLAMA_API="http://127.0.0.1:11434/api"
export OLLAMA_MODEL="qwen3:4b"
export OLLAMA_READ_TIMEOUT_SECONDS="600"
export OLLAMA_NUM_CTX="8192"
export OLLAMA_NUM_PREDICT="256"
export OLLAMA_BATCH_SIZE="10"
export AI_DEBUG_LOGS="1"
export AI_DEBUG_OUTPUT_CHARS="2000"
python -m server.app
```

이 앱은 로컬 키워드 기반 fallback을 사용하지 않습니다. `/api/run`은 반드시 로컬 Ollama API를 호출하고, 모델이 다음 형식의 JSON을 반환해야 점수를 계산합니다.

```json
{"delete_ids": [1, 2, 3]}
```

Windows PowerShell:

```powershell
$env:OLLAMA_API="http://127.0.0.1:11434/api"
$env:OLLAMA_MODEL="qwen3:4b"
$env:OLLAMA_READ_TIMEOUT_SECONDS="600"
$env:OLLAMA_NUM_CTX="8192"
$env:OLLAMA_NUM_PREDICT="256"
$env:OLLAMA_BATCH_SIZE="10"
$env:AI_DEBUG_LOGS="1"
$env:AI_DEBUG_OUTPUT_CHARS="2000"
python -m server.app
```

첫 실행은 모델 다운로드와 로딩 때문에 오래 걸릴 수 있습니다. 기본 read timeout은 `600`초입니다. Ollama 입력 프롬프트가 잘리지 않도록 이메일은 기본 10개씩 나누어 분석합니다.

Docker 실행 시 Gunicorn access log는 stdout으로 출력됩니다. Ollama 내부 로그는 `/tmp/ollama-runtime.log`에 저장되어 기본 컨테이너 로그를 길게 만들지 않습니다.

## 점수 방식

```text
TP = 악성 이메일을 삭제함
FP = 정상 이메일을 삭제함
FN = 악성 이메일을 삭제하지 못함
TN = 정상 이메일을 유지함

score = max(0, 1000 + TP*5 + TN - FP*45 - FN*70)
```

FN은 악성 이메일이 살아남은 것이므로 FP보다 더 큰 페널티를 줬습니다.

## 발표용 설명

이 사이트는 단순한 악성 이메일 퀴즈가 아니라, 사용자가 직접 사회공학 공격의 특징을 관찰하고 이를 자연어 보안 정책으로 정리하는 활동입니다. 같은 이메일 데이터셋이라도 어떤 프롬프트를 작성하느냐에 따라 AI의 탐지 결과가 달라지므로, AI 보안 자동화에서 프롬프트 설계가 실제 탐지 품질에 영향을 준다는 점을 체험할 수 있습니다.
