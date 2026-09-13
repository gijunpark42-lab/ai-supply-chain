# 새 PC에 Ask 스위치 옮기기 (컴퓨터가 바뀌거나 고장났을 때)

gijun42.com의 Ask는 "이 PC에서 도는 Claude Opus 러너"가 답한다. 그 러너와 스위치를 새 PC에
그대로 다시 박는 순서. 전부 무료이고 30분이면 끝난다. 웹사이트(Vercel)는 건드릴 게 없다.

## 준비물

| 것 | 어디서 |
|---|---|
| 이 저장소 | `git clone https://github.com/gijunpark42-lab/reticulum-ai.git` → `Desktop\earnings-ai` |
| Node.js 20 이상 | nodejs.org (LTS) |
| Claude Code CLI | `npm i -g @anthropic-ai/claude-code` 후 `claude` 한 번 실행해서 로그인 (구독 계정) |
| Tailscale | `winget install --id Tailscale.Tailscale` (무료 개인 플랜) |
| `ASK_SHARED_SECRET` | Vercel → reticulum-ai → Settings → Environment Variables 에서 값 복사 |

## 순서

1. **저장소 클론** 후 `local-ask\.env` 만들기: `.env.example` 복사해서 `ASK_SHARED_SECRET=` 에 Vercel 값 붙여넣기.
   (다른 줄은 그대로 둬도 됨.)
2. **Tailscale 로그인 (이름 유지가 핵심)**
   - 먼저 https://login.tailscale.com/admin/machines 에서 예전 `gijun-pc` 기기를 삭제(…메뉴 → Remove).
   - 새 PC에서: `"C:\Program Files\Tailscale\tailscale.exe" up --hostname gijun-pc --unattended` → 브라우저 로그인.
     (`--unattended` 필수. 없으면 Tailscale 앱이 안 붙어 있는 순간 연결이 끊긴다.)
   - 이름이 같으면 공개 주소도 `https://gijun-pc.tail362ef7.ts.net` 그대로라서 Vercel 설정을 안 바꿔도 된다.
     (이름을 못 지켜서 `gijun-pc-1` 같은 게 되면: Vercel의 `LOCAL_ASK_URL`을 새 주소로 바꾸고 Redeploy.)
3. **Funnel 켜기**: `"C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8787`
   (처음이면 링크가 뜨고 Enable 한 번. 서비스라 재부팅해도 유지됨.)
4. **스위치 설치**: `local-ask\switch\install-switch.cmd` 더블클릭.
   바탕화면에 `Ask Switch`가 생기고, 로그온할 때 러너가 자동 시작되도록 작업이 등록된다.
5. **확인**: 바탕화면 `Ask Switch` 더블클릭 → 세 줄(Runner / Tailscale / Public address)이 다 OK면 끝.
   gijun42.com에서 질문 하나 던져 보면 답 아래에 `claude-opus-5 · effort max · your machine`이 떠야 한다.

## 평소 쓰는 법

- 그냥 PC 켜 두면 된다. 로그온하면 러너 자동 시작, Tailscale 자동 연결.
- `Ask Switch`: 현재 상태(ON/OFF) 보여주고 Y 누르면 반대로 바꿔 준다.
- PC가 잠자기에 들어가면 답을 못 하니 전원 설정에서 잠자기를 끄는 게 좋다.
- **`node up.mjs`는 절대 실행하지 말 것** (Cloudflare 임시 주소로 Vercel 설정을 덮어씀).

## 이 PC에 뭐가 깔려 있는지 (2026-09-13 기준)

- 러너: `local-ask/server.mjs` (`claude -p --model opus --effort max`), 포트 8787, 로그 `local-ask/logs/`
- 자동 시작: Windows 작업 스케줄러 "local-ask runner" (로그온 시)
- 공개 주소: Tailscale Funnel `https://gijun-pc.tail362ef7.ts.net` → 127.0.0.1:8787 (테일넷 `gijunpark42-lab.github`)
- Vercel: `LOCAL_ASK_URL` = 위 주소, `ASK_SHARED_SECRET` = `.env`와 동일
- 스위치: 바탕화면 `Ask Switch.cmd` (원본은 `local-ask/switch/`)
