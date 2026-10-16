# AI-Compiler Convergence Watch

## (a) 한 줄 설명
"LLM이 컴파일러를 대체하는 게 아니라, 컴파일러/런타임을 '호출'하게 될 것이다"라는 트렌드가
실제로 **어디에 착지하고 있는지**를 매일 한 번 교차 관찰해, 새로운 증거가 있을 때만
텔레그램으로 알려주는 무인 레이더입니다. GitHub의 주요 컴파일러·텐서 런타임 프로젝트
(LLVM, Triton, TVM, PyTorch, JAX, Halide, wasmtime, ONNX Runtime) **공식 릴리스 노트**에
LLM/에이전트 관련 키워드가 등장하는 순간과, HackerNews에서 "compiler + AI" 조합으로 새로
올라오는 글을 함께 포착합니다.

## (b) 왜 이 트렌드에서 이 아이디어가 나왔는가
오늘의 트렌드 "LLMs Will Not Replace AI Compilers. They Will Call Them."은
(HN points=1, comments=0으로 신호는 약하지만) "LLM이 전통적인 컴파일러/최적화 도구를
직접 대체하는 대신, 도구로서 호출하게 될 것"이라는 주장을 담고 있습니다. 이 주장이
맞는지 틀린지는 블로그 글 하나로 알 수 없고, **실제로 주요 컴파일러 인프라 프로젝트들이
릴리스 노트에 LLM/에이전트 관련 기능을 언급하기 시작하는지**를 관찰해야 검증할 수 있습니다.

그래서 이 프로젝트는 "트렌드 글 요약"이나 "GitHub 트렌딩 저장소 큐레이션"(이미 만든 적 있음)
대신, **공식 릴리스 노트 diff + 커뮤니티 담론**이라는 전혀 다른 메커니즘으로 같은 트렌드를
추적합니다. 평소에는 아무 신호가 없으면 조용하고, 실제로 "LLM이 컴파일러를 호출한다"는
흐름이 코드베이스나 담론에 반영되는 순간에만 알림이 울립니다.

## 동작 방식
1. `watchlist.json`에 등록된 저장소들의 `releases.atom` 피드(GitHub 공식, 인증 불필요)를
   가져와 아직 알린 적 없는 릴리스 중 LLM/에이전트 관련 키워드(llm, gpt, agent, copilot,
   genai, autotuning 등)가 포함된 것만 추출
2. HackerNews Algolia 검색 API로 최근 3일 내 "AI compiler" / "LLM compiler" / "compiler agent"
   쿼리 결과 중, 제목에 "compiler"와 AI 관련 키워드가 함께 있는 신규 글만 추출
3. `data/seen_items.json`에 이미 알린 항목 ID를 저장해 중복 알림 방지
4. 새 항목이 있으면 텔레그램으로 전송, 없으면 조용히 종료 (수집/필터링 로그만 stdout에 출력)

## (c) 필요한 환경변수
| 변수 | 필수 여부 | 설명 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 선택 (있으면 텔레그램 전송, 없으면 콘솔 출력으로 자동 대체) | 기존 파이프라인에 이미 설정된 텔레그램 봇 토큰을 그대로 사용 |
| `TELEGRAM_CHAT_ID` | 선택 (있으면 텔레그램 전송, 없으면 콘솔 출력으로 자동 대체) | 기존 파이프라인에 이미 설정된 채팅 ID를 그대로 사용 |

새로운 API 키는 필요하지 않습니다 (GitHub Releases Atom 피드, HN Algolia 모두 무인증 공개 API).
감시 대상 저장소는 `watchlist.json`에서 자유롭게 추가/수정할 수 있습니다.

## (d) 실행 방법
```bash
pip install requests   # 이미 설치되어 있다면 생략 가능
export TELEGRAM_BOT_TOKEN=xxx   # 없어도 실행되며, 이 경우 콘솔에 리포트가 출력됩니다
export TELEGRAM_CHAT_ID=xxx
python3 run.py