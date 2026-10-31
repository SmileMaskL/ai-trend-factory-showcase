# AI 말투 신호 레이더 (Hacker News)

Hacker News 댓글에 "delve", "furthermore", "boilerplate 결론", 과다한
em-dash 같은 전형적인 **AI-tell 말투 패턴**이 하루 동안 얼마나 섞여 있는지를
수치화하고, 7일 평균 대비 오늘 급등했는지를 매일 한 번 텔레그램으로 알려주는
무인 스크립트입니다.

## 왜 이 아이디어인가 (트렌드 연결)

오늘의 트렌드는 HN의 "How do you deal with AI Output of your boss?" 글입니다.
요지는 "상사/동료가 보낸 글이 AI가 쓴 것 같다"는 판단을 어떻게 하느냐인데,
실제로 이런 판단은 대부분 몇 가지 눈에 익은 말투 패턴(delve, furthermore,
"it's worth noting", 기계적인 결론 문단, 과다한 em-dash 등)에 기반합니다.
이 프로젝트는 그 판단 기준을 코드로 정량화해서, "지금 온라인 담론에
이런 AI 말투가 얼마나 퍼져 있는지"를 매일 추적하는 레이더로 만들었습니다.
(이미 만든 프로젝트들과 달리, 특정 뉴스/릴리스를 큐레이션하는 게 아니라
*텍스트 자체의 언어적 신호를 매일 지수화·추세 비교*하는 방식입니다.)

## 환경변수

- `TELEGRAM_BOT_TOKEN` — 이미 파이프라인에 설정된 텔레그램 봇 토�큰을 그대로 사용 (추가 설정 불필요)
- `TELEGRAM_CHAT_ID` — 이미 파이프라인에 설정된 채팅 ID를 그대로 사용 (추가 설정 불필요)

새로운 외부 API 키는 필요 없습니다 (Hacker News 공식 Firebase API는 인증 불필요).

## 실행 방법

```bash
python3 run.py