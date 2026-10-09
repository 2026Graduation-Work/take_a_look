# 백업 위치·규칙

- **무엇을**: 운영에서 지우기 전의 데이터(Storage 입력 파일·DB 덤프 등)와 대용량 산출물. 레포에는 넣지 않는다.
- **어디에**: 팀 공유 Google Drive `take_a_look_backups/<항목>-<YYYY-MM-DD>/`(WSL에서는 `/mnt/g/…`). 로컬 `~/graduation/backups/`는 Drive로 옮기기 전 잠깐만 둔다.
- **누가**: 지우는 작업을 하는 사람이 백업하고, 같은 폴더에 `SHA256SUMS`(또는 `MANIFEST.json`)를 남긴다. 대용량 백업은 앞으로 Drive로만.
- **검증**: Drive에 복사한 뒤 `sha256sum -c`로 전부 맞을 때만 로컬 사본을 지운다. 운영 원본은 백업 해시가 운영 기록(DB `feature_sha256` 등)과 맞을 때만 지운다.
- **하지 않는 것**: GitHub Actions에서 Drive로 자동 업로드(계정 토큰 위임 보류). 비밀 값(.env·키)은 백업 폴더에 두지 않는다.
- **실제 경로·매니페스트**(2026-10-09): Drive `내 드라이브/Take a Look Data Storage/take_a_look_backups/`(바로가기, WSL에서는 `/mnt/g/.shortcut-targets-by-id/1QzP9xjw3oqUix__0GyTgNcafIPThsvag/Take a Look Data Storage/take_a_look_backups/` — 상위 두 폴더는 목록 권한이 없는 게 정상). 백업마다 원본 기준 상대 경로 sha256 목록 `backups-manifest-YYYYMMDD.sha256`을 로컬(`~/graduation/`)과 Drive 폴더에 함께 두고, 복사는 `rsync -rt`(`--delete` 금지, Drive가 시각 설정을 막아 code 23이 나도 `sha256sum -c` 통과면 정상), 로컬 삭제는 매니페스트로 원본을 다시 대조해 통과한 경로만 하나씩 지운다.
