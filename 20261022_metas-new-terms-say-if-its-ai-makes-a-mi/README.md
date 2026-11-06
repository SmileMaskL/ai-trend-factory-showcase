# AI 책임전가 조항 감시 레이더 (AI Liability-Shift Clause Watch)

## (a) 한 줄 설명
Hacker News에서 "AI 벤더가 자사 서비스의 오류 책임을 고객에게 떠넘기는 계약/약관 조항"이 공개적으로 논의되는 새 글을 매일 감지해 텔레그램으로 알려주는 무인 레이더입니다.

## (b) 왜 이 트렌드에서 이 아이디어가 나왔는가
오늘의 트렌드 주제는 "Meta's new terms say if its AI makes a mistake, it will be the customer's fault"입니다. 이는 단순한 "AI 서비스 가격/구독 변경"이나 "AI 규제 숫자 임계값" 이슈가 아니라, **AI 벤더가 계약서 상에서 법적 책임(liability)을 고객에게 전가하는 조항**이라는 매우 구체적이고 새로운 패턴입니다.

HN에서는 이런 뉴스가 처음엔 포인트/댓글 수가 낮게(이번 글도 points=2, comments=0) 시작했다가, 비슷한 사례(OpenAI, Microsoft, Google, Anthropic, AWS 등의 ToS 변경)가 반복되면 급격히 주목받는 경향이 있습니다. 즉, "책임전가 조항"이라는 카테고리 자체가 앞으로 반복될 가능성이 높은 신호 패턴이며, 기존에 만들어둔 프로젝트들(구독/가격 변경 레이더, 규제 숫자 임계값 레이더, 보안 사고 레이더 등)과는 겹치지 않는 **"계약/약관의 법적 책임 귀속 조항"**이라는 새로운 틈새입니다.

이 레이더는 특정 벤더 하나만 보는 게 아니라, 주요 AI 벤더 이름 + 책임/면책 관련 키워드가 함께 등장하는 HN 글을 매일 교차 필터링해서, 이런 패턴이 다시 나타날 때마다 가장 먼저 알려주는 것을 목표로 합니다.

## (c) 필요한 환경변수
- `TELEGRAM_BOT_TOKEN` : 기존 파이프라인에 이미 등록된 텔레그램 봇 토큰 (그대로 재사용)
- `TELEGRAM_CHAT_ID` : 기존 파이프라인에 이미 등록된 텔레그램 채팅 ID (그대로 재사용)

이 두 값 외에 추가로 필요한 API 키는 없습니다. Hacker News 검색은 인증이 필요 없는 무료 Algolia HN Search API(`https://hn.algolia.com/api/v1/search_by_date`)를 사용합니다.

## (d) 실행 방법
```bash
export TELEGRAM_BOT_TOKEN="..."   # 이미 설정되어 있다면 생략 가능
export TELEGRAM_CHAT_ID="..."     # 이미 설정되어 있다면 생략 가능
python3 run.py