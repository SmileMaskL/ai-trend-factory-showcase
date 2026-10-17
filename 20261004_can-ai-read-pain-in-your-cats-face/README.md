# Animal Pain-AI Radar

## (a) 한 줄 설명
"컴퓨터 비전/AI로 고양이·반려동물·가축의 표정에서 통증과 고통을 읽어내는 연구·제품"
흐름을 arXiv 신규 논문과 HackerNews 신규 토론에서 매일 한 번 교차 포착해, 새로운
신호가 있을 때만 텔레그램으로 알려주는 무인 레이더입니다.

## (b) 왜 이 트렌드에서 이 아이디어가 나왔는가
오늘의 트렌드 "Can AI read pain in your cat's face?"(HN points=1, comments=0으로
신호는 약함)는 Feline Grimace Scale류의 AI 기반 동물 표정 통증 인식을 다룹니다.
이 기사 한 건을 요약/번역해서 보내는 건 재사용성이 없고, 신호도 너무 약합니다.

대신 이 프로젝트는 "AI가 동물의 얼굴에서 통증/감정을 읽는다"는 더 큰 흐름이
**실제로 연구(arXiv)와 커뮤니티 담론(HN)에서 얼마나 자주, 새롭게 등장하는지**를
추적합니다. 이는 기존에 만든 프로젝트들(컴파일러 수렴, 에이전트 보안사고, 실험
의사결정 벤치마크, 인재 이동 규제, Moloch 지수, GitHub MCP/에이전트 레이더) 중
어느 것과도 주제·메커니즘이 겹치지 않는 완전히 새로운 레이더입니다.

## 동작 방식
1. arXiv Atom API로 `"grimace scale" / "animal pain" / "pain face" / "facial
   action unit" / "pain assessment"` 중 하나와 `"animal" / "veterinary" /
   "livestock" / "cat" / "dog" / "pet"` 중 하나를 함께 포함하는 최근 5일 내
   신규 논문만 수집
2. HackerNews Algolia 검색 API로 "pet animal veterinary AI pain welfare" 쿼리
   결과 중, 제목에 동물 관련 키워드와 AI/복지 관련 키워드가 함께 있는 신규 글만 추출
3. `data/seen_items.json`에 이미 알린 항목 ID를 저장해 중복 알림 방지 (60일 보존)
4. 새 항목이 있으면 텔레그램으로 전송, 없으면 조용히 종료
5. 텔레그램 자격증명이 없거나 전송이 실패하면 `data/latest_digest.txt`에 기록하는
   것으로 대체 — 사람 개입 없이도 항상 성공으로 끝나는 무인 실행 보장

## (c) 필요한 환경변수
| 변수 | 필수 여부 | 설명 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 선택 (있으면 텔레그램 전송, 없으면 `data/latest_digest.txt`로 대체) | 기존 파이프라인에 이미 설정된 텔레그램 봇 토큰을 그대로 사용 |
| `TELEGRAM_CHAT_ID` | 선택 (있으면 텔레그램 전송, 없으면 `data/latest_digest.txt`로 대체) | 기존 파이프라인에 이미 설정된 채팅 ID를 그대로 사용 |

새로운 API 키는 필요 없습니다 (arXiv Atom API, HN Algolia API 모두 무인증 공개 API).

## (d) 실행 방법
```bash
pip install requests   # 이미 설치되어 있다면 생략 가능
export TELEGRAM_BOT_TOKEN=xxx   # 없어도 실행되며, 이 경우 data/latest_digest.txt에 기록됩니다
export TELEGRAM_CHAT_ID=xxx
python3 run.py