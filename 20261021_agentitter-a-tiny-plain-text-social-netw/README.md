# Agent-Native Launch Radar

하루 1회 실행되어, Hacker News에서 "사람이 아니라 AI 에이전트가 직접 사용하도록
설계된" 신규 제품/서비스 런칭 신호만 걸러 텔레그램으로 다이제스트를 보내는
무인 큐레이션 레이더입니다.

## (a) 한 줄 설명
HN에서 "plain-text social network you use through your AI agent" 같은
agent-native 제품 런칭 신호를 매일 교차 포착해 텔레그램으로 알려주는 봇.

## (b) 왜 이 트렌드에서 이 아이디어가 나왔나
오늘의 트렌드 주제 "Agentitter – a tiny plain-text social network you use
through your AI agent"는 HN 포인트 1, 댓글 0으로 신호 자체는 미미하지만, 그
형태가 보여주는 트렌드는 주목할 만합니다: 최근 "사람용 UI가 아니라 AI 에이전트가
직접 써야 하는" 제품들(agent-native products)이 조용히 늘어나고 있습니다.
기존에 만든 프로젝트들은 MCP 오픈소스 저장소, AI 규제/정책, AI 말투 패턴 등을
다루지만, "에이전트를 최종 사용자로 삼는 제품 자체의 런칭"을 추적하는 것은
없었습니다. Agentitter처럼 낮은 트랙션에서 조용히 등장하는 이런 제품들을
조기에 포착해두면, 추후 "agent economy" 관련 뉴스레터/리스트의 소스가 됩니다.

## (c) 필요한 환경변수
- `TELEGRAM_BOT_TOKEN` : 기존 파이프라인에 등록된 텔레그램 봇 토큰 (이미 설정됨)
- `TELEGRAM_CHAT_ID` : 알림을 받을 텔레그램 채팅 ID (이미 설정됨)

추가 API 키 없이, Hacker News Algolia 공개 검색 API(무료, 인증 불필요)만 사용합니다.

## (d) 실행 방법
```bash
python3 run.py