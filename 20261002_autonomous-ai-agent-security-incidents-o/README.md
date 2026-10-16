# AI 에이전트 보안 사고(Security Incident) 레이더

HackerNews와 NVD(CVE) 공개 데이터를 매일 한 번 교차 검색해서, **"AI/LLM 에이전트"와 관련된 보안
사고·취약점·익스플로잇**만 걸러내고, 새로 발견된 항목이 있을 때만 텔레그램으로 알려주는 무인
알림 필터 봇입니다. 평소에는 조용하고, 실제로 관련 사고가 터졌을 때만 울립니다.

## 왜 이 트렌드에서 이 아이디어가 나왔는가

오늘의 트렌드 주제는 "Autonomous AI Agent Security Incidents of 2026: Dataset and Monograph"
(자율 AI 에이전트 보안 사고 데이터셋/논문)입니다. 이 자료가 암시하는 건 "AI 에이전트가 늘어나면서
보안 사고도 체계적으로 집계해야 할 만큼 쌓이고 있다"는 흐름입니다. 하지만 이런 사고 정보는
HackerNews, NVD, 각종 보안 블로그에 흩어져 있고, 매번 사람이 찾아보기엔 신호 대비 잡음이 큽니다.

그래서 이 프로젝트는 "AI 에이전트" + "보안 사고/취약점" 교차 조건으로만 필터링해서, 관련 없는
일반 AI 뉴스나 무관한 CVE는 걸러내고, 진짜 해당되는 사고만 알려주는 **좁고 뾰족한 필터**로
설계했습니다. (기존에 만든 "실험 의사결정 벤치마크", "인재 이동 제한 뉴스", "Moloch Index",
"GitHub MCP/에이전트 저장소 레이더"와는 주제·데이터소스가 모두 다릅니다.)

## 동작 방식

1. HackerNews Algolia 검색 API로 최근 2일 내 "AI agent" / "LLM agent" / "agentic" 관련 글 중
   보안 키워드(vulnerability, exploit, breach, incident, jailbreak 등)가 포함된 글만 추출
2. NVD CVE API에서 최근 2일 내 공개된 CVE 중 설명에 "agent"가 포함되고, AI 관련 키워드
   (LLM, GPT, autonomous, chatbot 등)와 함께 언급된 것만 추출
3. `data/seen_items.json`에 이미 알린 항목 ID를 저장해 중복 알림 방지
4. 새 항목이 있으면 텔레그램으로 전송, 없으면 조용히 종료 (API 호출/필터링 로그만 stdout에 출력)

## 필요한 환경변수

- `TELEGRAM_BOT_TOKEN`: 이미 파이프라인에 설정된 텔레그램 봇 토큰을 그대로 사용
- `TELEGRAM_CHAT_ID`: 이미 파이프라인에 설정된 채팅 ID를 그대로 사용

추가 API 키는 필요 없습니다 (HN Algolia, NVD 모두 무인증 공개 API).

## 실행 방법

```bash
python3 run.py