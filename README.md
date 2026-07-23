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

이미지에는 웹 앱만 들어 있습니다. Ollama와 모델은 호스트에 있는 것을 그대로 씁니다. 빌드할 때 모델을 내려받지 않으므로 이미지는 244MB 정도이고 빌드도 1분 안에 끝납니다.

호스트 Ollama가 컨테이너에서 보이도록 `0.0.0.0`으로 띄웁니다. 기본값인 `127.0.0.1`은 컨테이너에서 접근할 수 없습니다.

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

```bash
cd ai_email_prompting_detector
docker build -t ai-email-prompting-detector .
docker run --rm -p 5001:5001 \
  -e OLLAMA_MODEL=qwen3:4b \
  -v email-scores:/app/data \
  ai-email-prompting-detector
```

브라우저에서 접속:

```text
http://127.0.0.1:5001
```

모델은 호스트에서 미리 받아 두세요. 컨테이너는 시작할 때 호스트 Ollama에 연결해서 모델이 있는지 확인하고, 없으면 로그에 경고를 남깁니다.

```bash
ollama pull qwen3:4b
```

`host.docker.internal`은 Docker Desktop(macOS, Windows)에서 바로 동작합니다. Linux에서는 실행 옵션을 추가하세요.

```bash
docker run --rm -p 5001:5001 \
  --add-host=host.docker.internal:host-gateway \
  -v email-scores:/app/data \
  ai-email-prompting-detector
```

`OLLAMA_HOST=0.0.0.0`은 같은 네트워크의 다른 기기에서도 Ollama에 접근할 수 있게 만듭니다. 신뢰할 수 없는 네트워크에서는 방화벽으로 11434 포트를 막거나, Docker 대신 로컬 Python으로 실행하세요.

Apple Silicon에서는 컨테이너가 Metal을 쓸 수 없습니다. 이 구성은 추론을 호스트 Ollama가 맡으므로 GPU 가속이 그대로 유지됩니다.

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
export OLLAMA_NUM_PREDICT="2048"
export OLLAMA_BATCH_SIZE="25"
export OLLAMA_BATCH_RETRIES="1"
export OLLAMA_THINK="0"
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
$env:OLLAMA_NUM_PREDICT="2048"
$env:OLLAMA_BATCH_SIZE="25"
$env:OLLAMA_BATCH_RETRIES="1"
$env:OLLAMA_THINK="0"
$env:AI_DEBUG_LOGS="1"
$env:AI_DEBUG_OUTPUT_CHARS="2000"
python -m server.app
```

첫 실행은 모델 다운로드와 로딩 때문에 오래 걸릴 수 있습니다. 기본 read timeout은 `600`초입니다.

이메일은 기본 25개씩 묶어 분석합니다. `OLLAMA_THINK=0`이 기본값이라 모델은 thinking 없이 곧바로 JSON을 출력합니다. thinking을 켜면 묶음당 소요 시간이 4배 가까이 늘어나고 num_predict를 넘겨 최종 JSON이 잘릴 수 있으므로, 켜려면 `OLLAMA_NUM_PREDICT`도 함께 올리세요.

한 묶음의 응답이 JSON으로 읽히지 않으면 그 묶음을 절반으로 나눠 `OLLAMA_BATCH_RETRIES`번까지 다시 시도합니다. 모델이 묶음에 없는 id를 반환하면 그 id만 무시하고 나머지 분석은 계속합니다.

로컬에서 `python -m server.app`으로 실행할 때 Flask 디버거는 꺼져 있습니다. 개발 중 자동 리로드가 필요하면 `FLASK_DEBUG=1`을 설정하세요. 이 서버는 `0.0.0.0`에 바인딩되므로 신뢰할 수 없는 네트워크에서는 켜지 마세요.

Docker 실행 시 Gunicorn access log와 배치 진행 로그는 컨테이너 stdout으로 나옵니다 (`docker logs`). Ollama 자체 로그는 컨테이너가 아니라 호스트에서 `ollama serve`를 띄운 터미널에 남습니다.

## 여러 컴퓨터로 나눠서 처리

`OLLAMA_API`에 주소를 쉼표로 나열하면 배치가 여러 대에 분산됩니다. 대수만큼 시간이 줄어듭니다. 같은 기계 안에서 병렬로 돌리는 것은 GPU가 이미 포화라 아무 효과가 없지만, 다른 컴퓨터는 GPU와 메모리 대역폭이 따로라서 실제로 빨라집니다.

각 컴퓨터에서 Ollama를 외부 접속 가능하게 띄우고 같은 모델을 받아 둡니다.

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull qwen3:latest
```

그다음 주소를 나열해서 실행합니다.

```bash
docker run --rm -p 5001:5001 \
  -e OLLAMA_API="http://192.168.0.10:11434/api,http://192.168.0.11:11434/api,http://192.168.0.12:11434/api" \
  -e OLLAMA_MODEL=qwen3:latest \
  -v email-scores:/app/data \
  ai-email-prompting-detector
```

이메일 100개(4배치) 기준 예상 시간입니다.

| 컴퓨터 수 | 실행 시간 |
| --- | --- |
| 1대 | 약 60초 |
| 2대 | 약 30초 |
| 4대 | 약 15초 |

한 대가 꺼지거나 네트워크가 끊기면 그 배치는 살아있는 다른 컴퓨터가 이어받습니다. 실행 도중 노트북이 절전 모드로 들어가도 전체 실행이 죽지 않습니다. 다만 모델이 답을 이상하게 준 경우는 다른 컴퓨터에서도 똑같이 나오므로 넘기지 않고 그대로 처리합니다.

컨테이너를 시작할 때 나열한 호스트를 모두 점검해서 `n/m hosts ready`로 알려 줍니다.

## 한 판(round) 크기

`emails.json`의 500개는 전체 풀이고, 한 번의 실행은 그 중 `ROUND_SIZE`개만 채점합니다. 실행 시간은 모델이 읽어야 하는 이메일 수에 거의 비례합니다. 프롬프트를 읽는 시간이 전체의 90%이고 답을 생성하는 시간은 1초도 안 되기 때문에, 모델을 바꾸거나 배치를 키우는 것보다 이 값이 속도를 결정합니다.

| ROUND_SIZE | 실행 시간 (qwen3:latest, 8B) |
| --- | --- |
| 25 | 13.1초 |
| 35 | 18.6초 |
| 100 | 약 60초 (기본값) |
| 500 | 약 5분 |

메일함에는 언제나 풀 전체가 아니라 이번 판에 뽑힌 이메일만 표시됩니다. 참가자가 보는 메일과 AI가 채점받는 메일이 같아야 하기 때문입니다.

```bash
export ROUND_SIZE=100     # 0이면 500개 전체
export ROUND_SEED=round-1 # 같은 seed면 모두 같은 문제를 받음
```

같은 seed면 항상 같은 이메일이 뽑히므로, 한 서버에 접속한 모든 참가자가 동일한 문제로 겨루게 됩니다. 다음 판을 돌리려면 `ROUND_SEED`를 바꾸고 서버를 다시 시작하세요. 뽑을 때 악성 비율(21%)은 풀과 같게 유지합니다.

## 점수 방식

```text
TP = 악성 이메일을 삭제함
FP = 정상 이메일을 삭제함
FN = 악성 이메일을 삭제하지 못함
TN = 정상 이메일을 유지함

score = max(0, 1000 - FP*(1000/정상메일수) - FN*(1000/악성메일수))
```

페널티를 손으로 정하지 않고 판에서 유도합니다. **악성을 전부 놓치면 0점, 정상을 전부 지우면 0점**이 되도록 두 값을 잡으면 답이 하나로 정해집니다. 악성 메일이 소수(21%)라 FN 1개가 FP 1개보다 약 4배 무겁게 매겨집니다. "악성을 놓치는 게 더 나쁘다"는 원칙이 임의의 상수 없이 자동으로 나옵니다.

`ROUND_SIZE`를 바꾸거나 악성 비율을 바꿔도 다시 조정할 필요가 없고, **판 크기가 달라도 점수를 그대로 비교할 수 있습니다.**

| 실행 | 25개 | 100개 | 500개 |
| --- | --- | --- | --- |
| 만점 | 1000 | 1000 | 1000 |
| 악성 80% 탐지 + 정상 10% 오삭제 | 700 | 673 | 701 |
| 악성 100% 탐지 + 정상 40% 오삭제 | 600 | 608 | 600 |
| 아무것도 안 지움 | 0 | 0 | 0 |
| 전부 지움 | 0 | 0 | 0 |
| 대충 찍기 | 0 | 0 | 0 |

이 방식은 Youden's J 지수를 1000점으로 환산한 것과 같습니다. 아무 생각 없이 한쪽으로 몰아붙이는 전략은 전부 0점이 되므로, 점수를 올리려면 정상과 악성을 실제로 구분하는 프롬프트를 써야 합니다.

## 발표용 설명

이 사이트는 단순한 악성 이메일 퀴즈가 아니라, 사용자가 직접 사회공학 공격의 특징을 관찰하고 이를 자연어 보안 정책으로 정리하는 활동입니다. 같은 이메일 데이터셋이라도 어떤 프롬프트를 작성하느냐에 따라 AI의 탐지 결과가 달라지므로, AI 보안 자동화에서 프롬프트 설계가 실제 탐지 품질에 영향을 준다는 점을 체험할 수 있습니다.
