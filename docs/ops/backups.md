# 백업 위치·규칙

- **무엇을**: 운영에서 지우기 전의 데이터(Storage 입력 파일·DB 덤프 등)와 대용량 산출물. 레포에는 넣지 않는다.
- **어디에**: 팀 공유 Google Drive `take_a_look_backups/<항목>-<YYYY-MM-DD>/`(WSL에서는 `/mnt/g/…`). 로컬 `~/graduation/backups/`는 Drive로 옮기기 전 잠깐만 둔다.
- **누가**: 지우는 작업을 하는 사람이 백업하고, 같은 폴더에 `SHA256SUMS`(또는 `MANIFEST.json`)를 남긴다. 대용량 백업은 앞으로 Drive로만.
- **검증**: Drive에 복사한 뒤 `sha256sum -c`로 전부 맞을 때만 로컬 사본을 지운다. 운영 원본은 백업 해시가 운영 기록(DB `feature_sha256` 등)과 맞을 때만 지운다.
- **하지 않는 것**: GitHub Actions에서 Drive로 자동 업로드(계정 토큰 위임 보류). 비밀 값(.env·키)은 백업 폴더에 두지 않는다.
