# 설치 가이드

exe 파일 또는 GitHub 파일을 받아 새 PC에 설치할 때 아래 순서대로 진행합니다.
읽는 데 3분, 설치는 10분 안에 끝납니다.

## 0. 시작 전 확인 (제약사항)

설치 전에 아래 조건을 먼저 확인해야 합니다. 이에 해당하지 않으면 프로그램이 동작하지 않습니다.

1. **Windows 10/11 전용**입니다. (Mac 미지원)
2. **Claude Code가 설치되고 로그인되어 있어야 합니다.**
   - 이 프로그램은 자체 AI가 없고, 그 PC에 설치된 Claude Code를 빌려 분석을 실행합니다. 따라서 Claude 유료 구독이 있어야 하며, 분석(하루 1회)이 구독 사용량을 일부 소모합니다.
3. **분석 대상은 Claude Code 대화 기록뿐입니다.**
   - Claude Code(VSCode 확장, 터미널)로 작업한 기록은 PC에 파일로 남아 이 프로그램이 읽을 수 있습니다.
   - claude.ai 웹사이트/앱에서 나눈 대화는 PC에 저장되지 않아 읽지 못합니다.
4. 설치 직후에는 보여줄 내용이 없을 수 있습니다. Claude Code로 작업을 시작한 다음 날부터 정리가 쌓입니다.

## 1. 공통 선행: Claude Code 준비

이미 Claude Code를 쓰고 있다면 이 단계는 건너뜁니다.

1. [Claude Code 공식 안내](https://claude.com/claude-code)에 따라 설치합니다.
2. 터미널(명령 프롬프트)에서 `claude`를 실행해 로그인합니다.
3. 확인: `claude --version`이 버전을 출력하면 준비된 것입니다.

## 2. 방법 A — exe 파일로 설치 (권장, 가장 간단)

1. [Releases 페이지](../../releases)에서 `WorkStatus.exe`를 다운로드합니다.
2. **전용 폴더를 하나 만들어** 그 안에 exe를 둡니다. (예: `C:\WorkStatus`)
   - 할 일 목록·정리 파일이 exe 옆에 생성되기 때문에, 바탕화면에 그냥 두면 파일이 흩어집니다.
3. exe를 실행합니다. 처음이라 SmartScreen 파란 경고창이 뜨는 경우 → **[추가 정보] → [실행]**을 누르면 됩니다.
   - [실행] 버튼 자체가 없이 차단되는 경우: 그 PC는 Smart App Control이 켜져 있는 것입니다. 이 기능은 한 번 끄면 Windows를 재설치하기 전까지 다시 켤 수 없으므로, 끄지 말고 **방법 B**로 설치하는 것을 권합니다.
4. 창이 뜨면 **[새로고침]** 버튼을 누릅니다. 첫 정리가 만들어지는 데 2~4분 걸립니다.
5. (선택) 매일 아침 08:50 자동 분석을 원하면, 명령 프롬프트에서 한 번 실행합니다:
   ```
   cd C:\WorkStatus
   WorkStatus.exe --install-schedule
   ```
   등록 완료 안내창이 뜨면 성공입니다.
6. (선택) 본인 이름 설정: exe 옆에 `config.json` 파일을 만들어 아래처럼 적습니다.
   ```json
   { "user_name": "홍길동" }
   ```
7. (선택) 바탕화면 바로가기: exe 우클릭 → [보내기] → [바탕 화면에 바로 가기 만들기]

## 3. 방법 B — GitHub 파일 + Python으로 설치 (Smart App Control PC)

exe가 차단되는 PC에서 쓰는 방법입니다. Python 공식 설치본은 서명되어 있어 차단되지 않습니다.

1. [python.org/downloads](https://www.python.org/downloads/)에서 Python 3.13 이상을 설치합니다.
   - 설치 첫 화면에서 **"Add python.exe to PATH" 체크박스를 반드시 켭니다.** 안 켜면 이후 명령이 인식되지 않습니다.
2. 이 레포 첫 화면에서 [Code] → [Download ZIP]을 눌러 받고, 원하는 폴더에 풉니다. (예: `C:\WorkStatus`)
3. 명령 프롬프트에서 의존성을 설치합니다:
   ```
   pip install pillow
   ```
4. 실행:
   ```
   cd C:\WorkStatus
   pythonw app.py
   ```
5. (선택) 아침 자동 분석 등록 — 아래에서 두 경로를 본인 PC에 맞게 바꿔 한 번 실행합니다.
   `pythonw.exe` 위치는 `where pythonw`로 확인할 수 있습니다.
   ```
   schtasks /Create /TN WorkStatusDaily /SC DAILY /ST 08:50 /F /TR "\"C:\...\pythonw.exe\" \"C:\WorkStatus\analyze.py\""
   ```
6. (선택) 바로가기: 바탕화면 우클릭 → [새로 만들기] → [바로 가기], 항목 위치에
   `"C:\...\pythonw.exe" "C:\WorkStatus\app.py"` 입력. 아이콘은 [속성] → [아이콘 변경]에서 폴더 안 `app.ico` 선택.

## 4. 잘 안 될 때

| 증상 | 원인과 조치 |
|---|---|
| 하단에 "Claude Code CLI를 찾을 수 없습니다" | Claude Code가 설치되지 않았거나 로그인 전입니다. 1번 단계를 먼저 완료합니다. |
| 새로고침이 "실패"로 끝남 | 폴더 안 `logs\` 로그를 열어 원인을 확인합니다. 로그인이 만료된 경우 터미널에서 `claude`를 한 번 실행해 다시 로그인하면 됩니다. |
| 새로고침은 되는데 내용이 비어 있음 | 그 PC에 Claude Code 대화 기록이 아직 없는 것입니다. Claude Code로 작업한 뒤 다시 누르면 됩니다. |
| exe가 실행조차 안 됨 (경고창에 실행 버튼 없음) | Smart App Control 차단입니다. 방법 B로 설치합니다. |
| 글꼴이 어색함 | Pretendard 자동 설치가 실패하면 기본 글꼴로 대체됩니다. 동작에는 문제가 없으며, [Pretendard](https://github.com/orioncactus/pretendard)를 직접 설치하면 원래 모습이 됩니다. |
| 아침 자동 분석이 안 도는 것 같음 | 그 시각에 PC가 꺼져 있으면 실행되지 않습니다. 다만 프로그램을 열 때 마지막 분석이 20시간 넘게 지났으면 자동으로 새로고침이 시작되므로, 놓친 날도 창만 열면 따라잡습니다. |
