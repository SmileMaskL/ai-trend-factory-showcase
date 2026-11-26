---
layout: default
title: AI 자동화 도구 공장 — 검증된 무료 AI 알림 도구 모음
description: 매일 AI가 최신 AI 트렌드를 골라 무료 자동화 도구를 만들고, 14일 이상 안정적으로 실행된 것만 모은 쇼케이스 목록입니다. 텔레그램 알림 봇 설치 방법과 활용법을 함께 안내합니다.
lang: ko
---

{% comment %}
  이 파일은 직접 편집하지 않아도 됩니다.
  목록 본문은 자동화 파이프라인이 매일 갱신하는 README.md를 그대로 불러옵니다.
  (README.md가 바뀌면 이 페이지도 자동으로 최신 목록을 보여줍니다.)
  README.md 위·아래의 안내 글만 이 파일에서 관리합니다.
{% endcomment %}

{% comment %} README.md는 자동화가 매일 새로 쓰므로, 웹페이지에 보일 때만 아래 문구를 바꿔서 보여줍니다. {% endcomment %}
{% capture readme_text %}{% include_relative README.md %}{% endcapture %}
{{ readme_text | replace: "# AI 자동화 도구 공장 (자동 생성 쇼케이스)", "# AI 자동화 도구 공장 — 검증된 무료 AI 알림 도구 모음" | replace: "이 목록은 자동화 파이프라인이 매일 갱신합니다. 사람이 직접 편집하지 않습니다.", "이 목록은 14일 이상 매일 실제로 실행되어 안정성이 확인된 도구가 생길 때마다 갱신됩니다. 각 도구의 설치 방법은 아래 안내를 참고하세요." }}

## 이 쇼케이스는 어떻게 운영되나요?

이 저장소는 "AI가 매일 작은 도구를 만들면, 사람은 그중 실제로 쓸 만한 것만 골라 공개한다"는 실험입니다. 운영 방식은 다음 세 단계로 이루어집니다.

1. **트렌드 선정** — 매일 아침 Hacker News, GitHub, 기술 뉴스에서 화제가 된 AI 관련 이슈 하나를 고릅니다.
2. **도구 제작** — 그 이슈를 매일 지켜보고 싶은 사람을 위해, 변화가 생기면 텔레그램으로 알려 주는 작은 자동화 봇을 만듭니다.
3. **검증 후 공개** — 만든 도구를 바로 공개하지 않고, **최소 14일 동안 매일 실제로 자동 실행**해 오류 없이 돌아간 것만 위 목록에 올립니다. 중간에 실패하거나 쓸모없는 알림만 보내는 도구는 탈락합니다.

그래서 위 목록의 날짜는 "만들어진 날"이고, 실제 공개는 그로부터 2주 이상 지난 뒤입니다.

## 도구는 어떻게 쓰나요?

목록의 각 항목을 누르면 해당 도구의 설명 페이지로 이동합니다. 도구마다 세부 설정은 다르지만, 대부분 다음과 같은 공통 순서로 설치합니다.

1. **텔레그램 봇 만들기** — 텔레그램에서 `@BotFather`를 검색해 `/newbot` 명령으로 봇을 만들고, 발급되는 **봇 토큰**을 복사해 둡니다.
2. **내 채팅 ID 확인** — 만든 봇에게 아무 메시지나 보낸 뒤, 도구 설명에 안내된 방법으로 알림을 받을 **채팅 ID**를 확인합니다.
3. **실행 환경 준비** — 도구 폴더의 파일을 내려받아 Python으로 실행하거나, GitHub 저장소로 복사한 뒤 GitHub Actions의 예약 실행(schedule)을 켜면 PC를 꺼 두어도 매일 자동으로 돌아갑니다.
4. **비밀값 등록** — 봇 토큰과 채팅 ID는 코드에 직접 적지 말고, GitHub 저장소의 Settings → Secrets에 등록해 사용하세요. 토큰이 공개되면 다른 사람이 내 봇을 조종할 수 있습니다.

## 자주 묻는 질문

**Q. 정말 무료인가요?**
네. 모든 도구는 무료로 공개된 소스코드이며, GitHub Actions 무료 사용량 안에서 충분히 돌아가도록 가볍게 만들어졌습니다.

**Q. AI가 만든 코드라 위험하지 않나요?**
14일 이상 실제로 실행해 동작은 확인했지만, 모든 경우의 보안을 보장하지는 않습니다. 실행 전 코드를 한 번 훑어보고, 비밀값은 반드시 Secrets로 관리하세요. 개인정보나 금전이 걸린 용도로는 쓰지 않는 것을 권장합니다.

**Q. 알림이 너무 자주 와요.**
대부분의 도구는 "새로운 변화가 있을 때만" 알리도록 만들어져 있습니다. 그래도 많다면 각 도구 설명에 있는 키워드·임계값 설정을 조절해 보세요.

**Q. 이런 도구가 있었으면 좋겠어요.**
[GitHub 이슈](https://github.com/SmileMaskL/ai-trend-factory-showcase/issues)로 아이디어를 남겨 주세요. 반응이 좋은 주제는 다음 제작 후보에 반영합니다.

---

[개인정보처리방침](./privacy.html) · [문의·제안](https://github.com/SmileMaskL/ai-trend-factory-showcase/issues) · 운영자의 다른 무료 도구: [생활 계산기](https://smilemaskl.github.io/) · [지원금헌터](https://smilemaskl.github.io/benefit-hunter/) · [PixelBatch](https://smilemaskl.github.io/pixelbatch/) · [PulseGuard](https://smilemaskl.github.io/PulseGuard/) · [응급의료QR](https://smilemaskl.github.io/emergency-qr/)

<!-- [애드센스 승인 전까지 숨김] 쿠팡 파트너스 자바스크립트 배너 (AI 자동화 도구 공장, id 1059855)
<div class="coupang-banner" style="max-width:680px; margin:24px auto; text-align:center; overflow:hidden;">
  <script src="https://ads-partners.coupang.com/g.js"></script>
  <script>
    new PartnersCoupang.G({"id":1059855,"template":"carousel","trackingCode":"AF8068770","width":"680","height":"140","tsource":""});
  </script>
  <p style="font-size:12px; color:#6a737d; margin:6px 0 0;">이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</p>
</div>
-->
