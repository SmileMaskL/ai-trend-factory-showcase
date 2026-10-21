# LLM Serving Breaking-Change Radar

## (a) 한 줄 설명
vLLM, TGI, SGLang, Ollama, llama.cpp 등 주요 **LLM 서빙 엔진**과 openai-python,
anthropic-sdk-python, litellm 등 주요 **SDK**의 공식 GitHub 릴리스 노트를 매일
한 번 스캔해, "deprecated / breaking change / sunset / removed support" 같은
운영 리스크 키워드가 **새로** 등장했을 때만 텔레그램으로 알려주는 무인 알림 필터입니다.
평소에는 조용하고, 실제로 뭔가 깨질 조짐이 보일 때만 울립니다.

## (b) 왜 이 트렌드에서 이 아이디어가 나왔는가
오늘의 트렌드 "ServeLearnBench: How Well Can Agents Self-Improve from Serving
Experience?"(HN points=1, comments=0으로 신호는 약함)는 "에이전트가 실제 서빙
운영 경험을 통해 스스로 개선할 수 있는가"를 측정하는 벤치마크입니다. 이 주제를
"논문/벤치마크 자체를 큐레이션"하는 방식으로 다루면 이미 만든
"AI 에이전트의 실험 의사결정 벤치마크·논문·토론 레이더"와 컨셉이 겹칩니다.

그래서 방향을 바꿔, "서빙(serving) 경험"이라는 키워드가 가리키는 **실제 운영
인프라**(LLM을 서빙하는 엔진과 SDK)에 주목했습니다. 에이전트든 사람이든, 서빙
스택이 예고 없이 breaking change를 내면 운영 중인 서비스가 멈춥니다. 즉 이
프로젝트는 벤치마크를 추적하는 대신, 벤치마크가 다루는 그 "서빙 경험" 자체가
실제로 얼마나 자주, 어떻게 흔들리는지를 **운영 리스크 알림**으로 변환합니다
(요약기 대신 알림 필터, 리서치 큐레이션 대신 액셔너블 경보라는 점에서 기존
프로젝트들과 메커니즘이 다릅니다).

## 동작 방식
1. `watchlist.json`에 등록된 저장소들의 `releases.atom` 피드(GitHub 공식,
   인증 불필요)를 가져옴
2. 아직 알린 적 없는 릴리스 중 제목/본문에 breaking change 관련 키워드
   (deprecat, breaking change, sunset, removed support, incompatible,
   migration required, end-of-life 등)가 포함된 것만 추출
3. `data/seen_items.json`에 이미 알린 항목 ID를 저장해 중복 알림 방지
4. 새 항목이 있으면 매칭된 키워드와 함께 텔레그램으로 전송, 없으면 조용히 종료

## (c) 필요한 환경변수
| 변수 | 필수 여부 | 설명 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 선택 (있으면 텔레그램 전송, 없으면 콘솔 출력으로 자동 대체) | 기존 파이프라인에 이미 설정된 텔레그램 봇 토큰을 그대로 사용 |
| `TELEGRAM_CHAT_ID` | 선택 (있으면 텔레그램 전송, 없으면 콘솔 출력으로 자동 대체) | 기존 파이프라인에 이미 설정된 채팅 ID를 그대로 사용 |

새로운 API 키는 필요하지 않습니다 (GitHub Releases Atom 피드는 무인증 공개
엔드포인트). 감시 대상 저장소는 `watchlist.json`에서 자유롭게 추가/수정할 수
있습니다.

## (d) 실행 방법
```bash
pip install requests   # 이미 설치되어 있다면 생략 가능
export TELEGRAM_BOT_TOKEN=xxx   # 없어도 실행되며, 이 경우 콘솔에 리포트가 출력됩니다
export TELEGRAM_CHAT_ID=xxx
python3 run.py