# 관제 FMS 서버 개발 인수인계

> 원본: Claude Docs "관제 FMS 서버 개발 인수인계" (2026-10-20, 김재오)
> https://claude.ai/artifact/FNuZn8ExfpEhvcJddqm3Vt
> 관제 UI 시안 다음 단계인 서버와 DB 작업을 이어서 하기 위한 문서입니다.
> 참고 자료: 팀 설계서 "기판 검사·이송 시스템 설계"(토픽 명세, 상태머신, DB 초안), 관제 UI 시안 "기판 이송 관제 콘솔".

## 대화 규칙

- 사용자와는 **한국어**로 대화합니다. 코드 식별자는 영어로 둡니다.
- **git 커밋은 하지 않습니다.** 커밋은 사용자가 직접 합니다.
- 코드는 **Python 3.10에서도 동작하게** 씁니다(관제 PC의 ROS 2 Humble 기본 버전). 개발 PC(Windows)는 Python 3.14를 쓰므로 3.11 이상 전용 문법은 피합니다. 패키지 설치는 `python -m pip install -r requirements.txt`처럼 실행할 Python으로 직접 합니다.

## 최근 진행 요약 · 다음 할 일 (2026-10-29 갱신)

**지금 상태 한 줄**: 관제 화면은 **보기 전용**으로 줄였고(main.py의 `/fms/status`만 받음), DB매니저는 팀원 main.py 이름에 맞춤. 남은 것은 팀원의 `/fms/status` 발행과 우분투로 옮기기. 옮기는 순서는 **`UBUNTU_SETUP.md`**(10-29 다시 씀), 팀원과의 약속은 **`TEAM_INTERFACE.md`**(10-29 다시 씀).

**2026-10-27 ~ 10-29에 한 것 (구조 B: UI는 main.py를 거쳐 받음)**
- 팀 설계도(B): 관제 화면은 main.py에서 `/fms/status`로만 받고, 로봇 토픽을 직접 다루지 않음. DB 쓰기는 main.py → `db_manager.py` 하나. 카메라 MJPEG만 화면이 직접 받음.
- **app.py 정리 (10-27)**: main.py가 맡게 된 부분 삭제 — `/api/state`(STATE_EVENT) · `/api/inspections/simulate` · `save_inspection_result` · `POST /api/inspections` · `/api/inspections/retake`, `ros_bridge.py`의 `/vision/result` 구독, 화면의 시안 상태 버튼 · 검사대 시뮬레이션 버튼 · 재촬영 버튼 · 촬영 중 표시, `tools/run_inspector_with_fms.py`(임시 다리). 백업 `.backup/before-ui-split_20261027_1100/`.
- **db_manager.py를 팀원 main.py에 맞춤 (10-28)**: `insert_inspection_result(db_record)`(검사 저장 + `db_record["job_id"]`에 번호), `update_delivery_complete(job_id, elapsed_sec)`(이송 줄이 없으면 만들고 복귀 시작 · total_sec 기록), 별칭 `DBManager = DbManager`. 개발 PC MySQL에서 main.py 순서대로 시험 통과(시험 데이터 검사 #7 · #8, 이송 #6 · #7이 개발 DB에 남음).
- **`/fms/status` 받기 (10-28)**: `app.py` `MISSIONS`(mission_state → 한글) · `update_fms(data)` · `snapshot()`의 `fms`, `/api/robot`에 `{"fms": {...}}` 시험 입구. `ros_bridge.py`는 `/fms/status` 하나만 구독(`/robot/status` · `/battery_state` 구독 삭제). `app.js` `showFms()`: 받으면 배지 · 지도 위치(`yaw_deg`→rad) · 속도 · 배터리를 실제 값으로, 못 받았으면 시안 애니메이션 그대로. 브라우저(메모리 모드)에서 확인, WSL 실제 토픽 시험은 안 함. 백업 `.backup/before-fms-status_20261028_*/`.
- **비상 정지 버튼 삭제 (10-29)**: UI가 `/cmd_vel/lock`을 보내면 안 되고 `/fms/command`도 main.py에 없어서, 화면 버튼 · `/api/estop` · `/api/estop/release` · `/cmd_vel/lock` 발행 삭제. 상단에 "비상 정지 · main.py 창에서 R" 안내만. `/fms/command`는 **만들지 않기로 함**(적재 · 하역 · 비상 정지 모두 main.py 창의 L · U · R 키). DB의 `ESTOP` 이벤트 종류는 남김. 백업 `.backup/before-remove-estop_20261029_0912/`.
- **DB 위치 결정 (10-29)**: 우분투 관제 PC 로컬 MySQL(`127.0.0.1`). 내 PC에 두는 안(원격 계정 `fms_app@'192.168.0.%'` · 방화벽 3306 · IP 고정 · 절전 끄기)은 복잡해서 안 씀. Workbench는 우분투에 설치 안 함.
- **팀원 main.py 커밋 반영 (10-29)**: L · U 키가 로봇 상태 확인 후 `LOAD_PASS`/`LOAD_FAIL` · `UNLOAD_DONE`, 배차 때 판정 대신 `CALL`만, 시리얼 `/dev/ttyACM0`, 모델 `/weights/best.pt`(최상위 폴더 — 상대 경로 의도인지 확인 중). db_manager 호출은 그대로. → **두 번째 커밋(10-29)**: `/fms/status` 0.5초 발행 추가, 모델 `main.py 옆 weights/best.pt`, 시리얼 9600, 검사 사진 경로가 절대 경로(→ `app.py` `photo_name()`이 `FMS_SNAPSHOT_DIR` 기준으로 바꿈). 남은 버그: 모서리 그리기에서 `np`를 카메라 없는 분기에서만 import → 맨 위 `import numpy as np` 필요(팀원에게 전달). 새 상태 `MOVING_TO_INSPECT` · `MOVING_TO_DEST`를 `MISSIONS`에 추가(6개).
- 문서 정리 (10-29): `UBUNTU_SETUP.md` · `TEAM_INTERFACE.md` 다시 씀, 이 파일 갱신. 백업 `.backup/before-docs_20261029_0928/`.
- **DB 읽기 방식 (나) 채택 (10-29 오후)**: (가) main.py가 DB 정보를 `/fms/status`에 담아 전달 vs (나) 화면이 직접 읽기를 비교 → **(나), 그중 화면 서버가 `store.py`로 MySQL을 직접 읽는 방식**(DB매니저 안 거침, db_manager에 읽기 함수 추가 안 함). main.py 추가 작업 없음, 이벤트 기록 창(날짜 · 종류 필터)은 그대로, `.env`는 `fms_manager/` · `fms_ui/` 두 곳. 비교 근거는 Claude 문서 "관제 화면 DB 정보 전달 방식 비교 (가)·(나)"(https://claude.ai/artifact/EobnB768e89fjrxNFqN9Vv, 팀원 공유 전).
  - 코드 정리: `store.py`를 읽기 전용으로(쓰기 함수 `open_event` · `close_event` · `record_result` · `simulate_inspection` · `retake`, `RetakeRejected` · `_fake_result` · `parse_insp_id` · `import random` 삭제). `app.py` `robot_link()`가 통신 끊김을 DB에 기록하지 않음(`robot["comm_lost"]` 삭제) — 통신 끊김 기록은 main.py 몫(선택). 메모리 · 개발 MySQL 모드 모두 `/api/status` · 통신 끊김 화면 · 이벤트 기록 창 확인. 백업 `.backup/before-store-readonly_20261029_1417/`.

**다음 할 일 (2026-10-29)**
1. 팀원에게 전달: 비교 문서(공유 후 링크) · main.py `np` import 버그 · `fms_manager/.gitignore`(`.env` · `logs/` · `latest_inspection_result.jpg`) · (선택) 배터리 반올림 없이 · 처음 값 `None` · `robot.last_seen` · `try/except` · 상태 이름이 6개 말고 더 있는지 · R 키 뜻 · 구역 좌표 · AMCL 지도 · 통신 끊김 DB 기록 여부 (`TEAM_INTERFACE.md` 4번).
2. 협업 저장소 `HD243017/turtlebot_vision_amr`에 올리기(사용자): 브랜치 `feature/fms-ui`, 이 폴더 → `fms_ui/`, `db_manager.py` → `fms_manager/`, PR. `.env` · `.backup/` 제외. 우분투 폴더 구성은 `~/turtlebot_vision_amr/fms_manager`(main.py · 검사 · `weights/best.pt` · `db_manager.py` · `.env` · `logs/`) + `~/turtlebot_vision_amr/fms_ui`(화면 서버 · `.env`).
3. 우분투에서 `UBUNTU_SETUP.md` 0~8단계.
4. `/fms/status`가 오면: 실물 확인, 시안 코드 정리("ROS 연동 때 정리 목록"), 계획 경로 · 작업 번호 표시(main.py가 보내 주면).

---

**(이하 10-26 기록)**

**2026-10-23 ~ 10-26에 한 것**
- 10-23: `.env` 만들어 MySQL 모드 확인(웹캠 검사 #0001 저장) · 로봇 칸에서 전방 감지 · 주행 제어 · 작업 단계 막대 삭제 · 배터리 · 통신 표시(서버 판단 + 화면) 사용자가 단계별 작성.
- 10-26: **ROS 토픽 받기**(`ros_bridge.py`, 도메인 22, WSL 시험 통과) · **실제 지도 `map_test1`로 교체**(구역 좌표는 임시) · 옮기기 전 개선(비상 정지 실패 경고창, 지도 · 구역 파일 오류에도 서버 켜짐, `.env.example`에 우분투 설정 예시) · `UBUNTU_SETUP.md` 작성.
- 10-26 사용자가 바탕화면 `관제3.zip`(fmsUI + webcam)을 만듦 → 지금 폴더와 **파일 내용 전부 같음** 확인(없는 건 `.vscode`, `.claude` 실행 설정뿐 — 우분투에선 안 씀). ⚠ zip 안에 `.env`(개발 PC DB 비밀번호) 포함 → 공유 금지, 우분투에서는 `.env`를 우분투 값으로 새로 고쳐야 함. `.backup/`도 들어 있음(실행엔 불필요).

**배치 결정 · 논의 (2026-10-26)**
- 기본 계획 유지: **서버 · MySQL · 검사 프로그램 · ROS 모두 우분투 관제 PC**, 다른 PC는 브라우저로 보기만. DB는 서버 PC의 **로컬 MySQL**(127.0.0.1) 하나면 됨 — 브라우저를 여는 PC 수와 무관, DB 서버 불필요.
- 개발 PC DB와 우분투 DB는 별개(데이터 안 넘어감). 필요하면 `sudo mysqldump fms > fms_backup.sql`로 가져옴.
- 사용자가 물어본 대안(**구현 안 함**, 필요 시 참고):
  - "서버는 내 PC, 웹캠 · 검사는 우분투": 지금 코드로는 아무것도 안 넘어옴(팀원 코드는 결과를 안 보내고, 임시 다리로 보내도 사진 파일이 내 PC에 없어 400 거절). 하려면 `save_inspection_result`의 파일 존재 확인을 끄는 설정(`FMS_PHOTO_REMOTE`) + 우분투 `python3 -m http.server 8090`로 사진 폴더 공개 + 화면이 그 주소에서 사진을 직접 읽는 설정(`FMS_PHOTO_URL`) + Windows 방화벽 5000 + 우분투에서 `FMS_URL=http://내PC_IP:5000/api/inspections`로 임시 다리 실행.
  - 내 PC(Windows)에서 터틀봇 토픽 받기: Windows엔 ROS(rclpy · DDS)가 없어 불가. 방법은 우분투 `rosbridge_server`(9090) + 내 PC `roslibpy`(추천), WSL 미러 네트워크, Windows용 ROS 설치(비추천).
  - 사진까지 토픽으로 보낼 때는 `/vision/result` JSON에 base64 JPEG를 같이 넣는 방식(짝 안 어긋남)을 추천.
- 웹 화면에는 **실제 촬영 버튼이 없음**(재촬영 · "검사대에 기판 올리기"는 가짜 결과). 웹에서 촬영하려면 "촬영 요청 → 임시 다리가 받아 스페이스바처럼 촬영" 기능을 만들어야 함(= 재촬영 실연동과 같은 일, 미구현).

**역할 분담 변경 (2026-10-26 오후, 팀 설계도)**: 팀원이 터틀봇 · A\* · 검사대 · **`main.py`**를 다시 작업하고, 사용자는 **UI(화면 + 화면 서버) · DB매니저(`store.py` → `db_manager.py` 예정) · DB**만 담당. DB는 관제 PC 밖에 둘 수 있음(`.env` `FMS_DB_HOST`만 변경, DB PC에서 원격 접속 · 계정 · 3306 방화벽 설정). 팀원에게 줄 연결 약속 제안서 **`TEAM_INTERFACE.md`** 작성(`/fms/status` · `/fms/command` 토픽, DB매니저 함수 목록, 테이블별 칸과 채우는 쪽, 질문 8개) → **팀원 답 대기 중**. 답이 오면 `db_manager.py` 작성과 `app.py`를 화면 서버로 줄이는 작업을 이어서 함.

## 현재 저장소 상태 (2026-10-29 갱신)

- 시안 HTML을 Flask로 옮긴 버전입니다: `app.py`, `store.py`, `db_manager.py`, `fms_map.py`, `ros_bridge.py`, `templates/`, `static/`, `db/`, `config/`, `maps/`, `snapshots/`, `tools/`, `UBUNTU_SETUP.md`, `TEAM_INTERFACE.md`.
- **관제 화면은 보기 전용**(2026-10-29): 로봇 쪽으로 보내는 토픽 · 버튼이 없음. 비상 정지 · 적재 · 하역은 main.py 창의 R · L · U 키.
- **ROS**: `ros_bridge.py`가 `/fms/status`(main.py의 `system_state` JSON) 하나만 구독 → `app.py` `update_fms()`(2026-10-28, `FMS_ROS=1`, 도메인 22). main.py가 아직 발행하지 않아 실물 미확인 — 받기 전에는 화면이 시안 애니메이션 · "수신 없음".
- **DB**: 쓰기는 main.py → `db_manager.py`, 화면은 `store.py`로 직접 읽기만(**MySQL 또는 메모리 가짜 데이터**, 아래 "DB" 참고). (나) 방식 확정(2026-10-29) — `store.py`에는 쓰기 함수가 없고, 화면은 통신 끊김도 DB에 쓰지 않음. 아래 "DB" 절의 "DB에 쓰는 것"은 옛 기록.
- **터틀봇 카메라 영상은 연결됨**: 카메라 칸이 web_video_server MJPEG 주소를 직접 띄움(아래 "팀 환경 정보").
- 아래 목표 구조와 다른 점(다음 작업 대상):
  - 실시간 갱신이 Flask-SocketIO가 아니라 `/api/status` **2초 폴링**입니다.
  - 이벤트 기록이 `/events` 별도 페이지가 아니라 메인 화면 안의 **모달 창**입니다. (상단 "이벤트 기록" 버튼은 **유지하기로 결정**, 2026-10-22)
  - `app.run(debug=True)` 라서 reloader가 켜져 있습니다. rclpy를 붙일 때는 `use_reloader=False`가 필요합니다.
  - 시안 미리보기 줄에는 "발표 모드" 버튼만 남음(2026-10-27). 지도 애니메이션 · 작업 #40 · `STATES`(안전 정지 · 통신 끊김 화면)는 `/fms/status` 실물 확인 뒤 정리.
- 개발은 Windows PC에서 하고, 실제 운영은 관제 PC(Ubuntu 22.04 + ROS 2 Humble)에서 합니다.
- **실행 방법** (`.vscode/launch.json`):
  - 개발용 "Flask: 관제 콘솔 실행" / "웹캠 사진 폴더로 실행 (시험용)": 디버그 모드, `127.0.0.1`(이 PC만). `python app.py`(▷)도 같음. (TurtleBot3 World 설정은 2026-10-26 지도 교체 때 삭제)
  - 공유용 "공유용: 관제 콘솔" / "공유용: 웹캠 사진 폴더": 디버그 · 자동 재시작 끔, `0.0.0.0`(같은 네트워크의 다른 PC가 `http://이PC의IP:5000`으로 접속). 디버그 모드를 네트워크에 열지 않습니다(디버그 화면에서 코드 실행 가능).
  - 로그인은 없지만 화면에 로봇을 움직이는 버튼이 없어(2026-10-29) 주소를 아는 사람은 보기만 할 수 있습니다.
- **검사 사진** (2026-10-22 갱신):
  - 팀원 검사 프로그램(`webcam/pcb_cv_inspector3_2.py`)이 검사마다 **상자 · 판정 글자가 그려진 사진 한 장**을 `logs/pass/` 또는 `logs/fail/`에 저장하고(`img_pass_YYYYmmdd_HHMMSS_0001.jpg`), DB에는 그 경로(`logs/pass/...`)만 들어갑니다. 경로는 **실행 위치 기준**이라 검사 프로그램은 반드시 webcam 폴더에서 실행.
  - 메인 화면 스냅샷 칸이 `/snapshots/<img_path>`로 사진을 보여 줍니다. 관제 서버의 `FMS_SNAPSHOT_DIR`을 webcam 폴더로 지정(실행 설정 "웹캠 사진 폴더" 두 개). 파일이 없으면 "사진 없음".
  - ~~상단 "검사 화면" 버튼 · 새 창 `/inspect`~~ → **2026-10-22 삭제**: 2안에서 상자 사진 칸이 빠져 메인 스냅샷과 같은 사진만 보여 줘서 겹침. 실시간 검출 화면은 같은 관제 PC의 검사 프로그램 OpenCV 창으로 봄. `FMS_INSPECT_STREAM` 설정도 삭제. 되살릴 때는 `.backup/before-remove-inspect_20261022_1700/`.
  - 시안용 샘플 사진: `snapshots/sample_board.jpg`, `sample_board_ng_box.jpg`, `sample_board_ok_box.jpg` (git에는 `sample_*`만 포함).
- ~~검사 결과 영역의 재촬영 버튼~~ → **2026-10-27 삭제**(검사 · 재촬영은 main.py 쪽). 우분투에서는 검사 사진이 `~/turtlebot_vision_amr/fms_manager/logs/...`에 쌓이므로 `FMS_SNAPSHOT_DIR`은 그 `fms_manager` 폴더(절대 경로).

## 서버 착수 전 확정할 것

서버는 로봇이나 실제 지도 없이 가짜 데이터로 먼저 만들 수 있습니다. 다만 아래 세 가지가 바뀌면 서버 코드도 같이 고쳐야 하므로, 팀에서 확정한 뒤 시작합니다.

- [ ] **로봇 상태 이름 목록**: `/robot/status`의 state 값. 설계서 상태머신(IDLE, PLANNING, FOLLOWING, DOCKING, WAIT_OPERATOR, SAFETY_STOP, ERROR)과 화면의 7단계(대기 → 검사대로 이동 → 도킹 → 적재 대기 → 이송 중 → 하역 대기 → 복귀)가 다릅니다. 하나로 맞추거나, 화면용 단계는 FMS가 "주행 상태 + 작업 단계"로 조합하도록 정합니다.
- [ ] **메시지 형식**: `/robot/status`, `/vision/result`의 JSON 필드(위치, 작업 번호, 검사 결과, 사진 경로).
- [ ] **DB 테이블**: 설계서 초안(inspection, delivery, safety_event)을 그대로 쓸지, 통신 이벤트용 테이블을 추가할지.

| 시기 | 할 일 |
|---|---|
| 1주차 | 위 세 가지 확정, 가짜 데이터로 서버와 화면 연결 |
| 2주차 통합 | 가짜 데이터를 실제 토픽으로 하나씩 교체, 맵핑한 지도 적용 |

## 팀 환경 정보 (2026-10-21, 팀원 가이드 기준)

> 계정 · 비밀번호는 이 문서와 git에 적지 않습니다. 팀원 가이드를 직접 보세요.

| 항목 | 값 |
|---|---|
| 리눅스 PC (web_video_server 실행) | `192.168.0.42` |
| 카메라 영상 주소 (MJPEG) | `http://192.168.0.42:8080/stream?topic=/image_raw&type=mjpeg` |
| 영상 서버 첫 화면 (토픽 목록) | `http://192.168.0.42:8080` |
| 터틀봇3 waffle_pi (라즈베리파이) | `192.168.0.154` |
| 카메라 토픽 | `/image_raw/compressed` · `sensor_msgs/msg/CompressedImage` · 320×240 (4:3) |
| ROS_DOMAIN_ID | 가이드는 **22** (아래 확인 필요 참고) |

영상 서버 준비 (리눅스 PC, 팀원 가이드):
```bash
sudo apt update
sudo apt install ros-humble-web-video-server
ros2 run web_video_server web_video_server
sudo ufw allow 8080/tcp
```

**카메라 방식 변경**: 원래 계획(Flask가 압축 토픽을 받아 MJPEG 라우트로 전달) 대신, 팀원이 띄운 **web_video_server의 MJPEG 주소를 화면 카메라 칸의 `<img>`에 직접 연결**합니다. Flask에 카메라 라우트는 만들지 않습니다. 카메라 칸 연결은 **사용자가 직접 작업**합니다(요청받기 전에는 손대지 않음).

**확인 필요**
- [x] **ROS_DOMAIN_ID = 22로 확정** (2026-10-26, 사용자). 인수인계 문서의 `11`은 쓰지 않음. 관제 서버를 켜는 터미널에서 `export ROS_DOMAIN_ID=22` (코드에는 넣지 않음).
- [ ] **카메라 토픽 이름**: 가이드는 `/image_raw/compressed`, 인수인계 문서는 `/camera/image_raw/compressed`. 실제 로봇 기준인 가이드 쪽이 맞을 가능성이 큽니다.
- [ ] **와이파이 대역폭**: 영상 주소가 원본 `topic=/image_raw`를 가리킵니다. 영상 서버가 로봇과 다른 PC면 압축 안 된 영상이 와이파이로 넘어올 수 있으니, `&default_transport=compressed`로 압축 토픽을 쓰는지 팀원과 확인합니다.
  - **2026-10-22 실측**: `&default_transport=compressed`를 붙이면 영상 서버가 연결만 받고 화면을 0장 보냄(리눅스 PC에 `ros-humble-image-transport-plugins`가 없는 것으로 추정). 옵션 없이는 초당 약 30장 정상. 그래서 카메라 칸 주소에서 **옵션을 뺐고**, 관제 화면에 터틀봇 영상이 나오는 것을 확인함. 와이파이 부담이 문제되면 리눅스 PC에 위 패키지를 설치한 뒤 옵션을 다시 붙입니다.
- [ ] 영상이 끊기면 카메라 칸을 "영상 신호 없음"으로 바꾸는 처리(`<img>`의 오류 이벤트)가 필요합니다.

## 토픽 인터페이스

> **2026-10-29 변경**: 관제 화면은 아래 토픽을 직접 받지 않고 main.py의 `/fms/status` 하나만 받습니다(B 구조, `TEAM_INTERFACE.md`). 비상 정지 `/cmd_vel/lock` 발행도 하지 않습니다. 아래 표는 처음 설계 기록이며, 지금은 main.py가 이 토픽들을 받아 `system_state`로 모읍니다. 카메라(web_video_server)만 화면이 직접 씁니다.

관제 서버는 관제 PC에서 FMS와 같은 프로세스(또는 연결 노드)로 돌며 아래 토픽만 사용합니다. 터틀봇과는 와이파이(`ROS_DOMAIN_ID=11`, 팀원 가이드는 22 — 위 "확인 필요" 참고)로 연결됩니다.

| 화면 요소 | 토픽 | 타입 | 방향 |
|---|---|---|---|
| 로봇 상태, 위치, 작업 단계 | `/robot/status` | std_msgs/String (JSON) | 구독 |
| 검사 결과 | `/vision/result` | std_msgs/String (JSON) | 구독 |
| 전방 감지 | `/yolo/front_obj` | std_msgs/String | 구독 |
| 배터리 | `/battery_state` | sensor_msgs/BatteryState | 구독 |
| 속도 | `/odom` | nav_msgs/Odometry | 구독 |
| 가장 가까운 물체 | `/scan` | sensor_msgs/LaserScan | 구독 (1~2Hz로 줄여 전송) |
| 전방 카메라 | `/camera/image_raw/compressed` (가이드: `/image_raw/compressed`) | sensor_msgs/CompressedImage | web_video_server가 구독, 화면은 MJPEG 주소로 표시 |
| 비상 정지 | `/cmd_vel/lock` | std_msgs/Bool | 발행 |

- **검사대 카메라**는 라이브로 보내지 않습니다. 와이파이 대역폭 문제로 320 폭 스냅샷만 저장하고, `/vision/result`의 사진 경로로 화면에 표시합니다.
- **적재 완료 / 수거 완료**는 관제 화면에서 받지 않습니다. 로봇 내장 버튼이나 별도 앱으로 처리합니다.
- **배터리 %**: percentage 필드가 비어 있을 수 있으니 먼저 확인하고, 비어 있으면 전압으로 계산합니다(3셀 LiPo: 12.6V = 100%, 11.0V 근처 = 경고).

## 관제 화면 구성

화면은 1920×1080 한 화면에 3열로 나뉩니다. 사용자는 작업자 겸 관제 담당 1명이고, 시연 때는 프로젝터에 화면 복제로 띄웁니다.

| 위치 | 영역 | 내용 |
|---|---|---|
| 상단바 | 이름 · 오늘 요약 · 버튼 | 오늘 검사 수 · OK 비율 · 평균 이송 시간 한 줄, 이벤트 기록 버튼, ~~비상 정지(가장 눈에 띄게)~~ → **2026-10-29 버튼 삭제**, "비상 정지 · main.py 창에서 R" 안내만 |
| 상단바 아래 | 경보 배너 | 안전 정지 · 통신 끊김 · 비상 정지 때만 표시 |
| 1열 | 지도 · 내비게이션 | 지도, 터틀봇 위치와 방향, 계획 경로, 구역과 마커(대기 · 검사대 · 양품 · 불량), 목적지 · 남은 거리 · 위치 인식 한 줄 |
| 2열 | 로봇 · 실시간 | 전방 카메라(320×240, 감지 결과 표시), 상태 · 통신 · 배터리 · 속도. ~~전방 감지 · 주행 제어 줄, 작업 단계 막대~~ → **2026-10-23 삭제**(사용자 요청, 백업 `.backup/before-trim-robot-panel_20261023_0949/`). 카메라 위 "전방 감지 없음/사람 감지" 표시와 `app.py`의 `STATES`는 남김, `STEPS`는 삭제 |
| 3열 | 검사 결과 · 스냅샷 | 세로로 긴 기판 사진, OK/NG, 불량 종류, 판정 방식(CV/AI), 이송 목적지, 최근 6건 |
| 별도 창 | 이벤트 기록 | 버튼을 눌렀을 때만 DB 조회, 날짜 · 종류 필터, 최신 순 최대 50건 |

**상태별 화면**
- **평상시**: 차분한 중립색, 로봇 상태 배지만 색으로 구분.
- **보행자 감지 → 안전 정지**: 주황 배너와 정지 경과 시간, 카메라 테두리 주황, 지도에 사람 아이콘.
- **로봇 통신 끊김**: 로봇을 마지막 위치에 흐리게, 수치 회색, 카메라 "영상 신호 없음", 빨간 배너와 무응답 시간.
- **비상 정지**: 버튼이 "비상 정지 중 · 해제…"로 바뀌고, 해제는 한 번 더 확인.
- **발표 모드**: 프로젝터용 밝은 고대비 + 큰 글자(CSS 클래스 전환).

**넣지 않기로 한 것**: 작업 대기열(상태 큐와 스케줄이 겹쳐 예외 처리가 어려워짐), 검사대 라이브 영상, 작업자 확인 버튼, 상단 부가 위젯(시계 등), 메인 화면의 실시간 이벤트 로그.

## 작업자 화면 표기 원칙

작업자 화면에는 코드값 대신 뜻을 한글로 표시합니다. 숨긴 값은 서버와 DB에서는 그대로 쓰고, 필요하면 개발자용 화면이나 로그에서 봅니다.

| 내부 값 | 화면 표기 |
|---|---|
| 상태 코드 (MOVING_TO_DEST 등) | 한글 배지만 (이송 중). 통신 끊김 때만 "마지막 상태: 이송 중" |
| x · y · yaw, AMCL | 목적지 · 남은 거리 · 위치 인식 정상 |
| 아루코 ID | 마커 0~3 |
| YOLO · person 0.91 / none | 사람 감지 / 전방 감지 없음 |
| 해상도 · fps | 표시 안 함 |
| ping | 응답 ○○ ms |
| 배터리 전압 | % 만 |
| 회전 속도 rad/s | 표시 안 함 (속도 m/s만) |
| 라이다 최근접 | 가장 가까운 물체 |
| cmd_vel AUTO / LOCKED | 주행 제어: 자동 주행 / 자동 주행 · 일시 정지 / 잠김 (비상 정지) |
| 불량 코드 MISSING | 부품 누락 |
| 템플릿 매칭 | CV · 기준 이미지와 비교 |
| 이미지 파일명 | 표시 안 함 |
| 동적맵 등록 후 재탐색 | 우회 경로로 다시 출발 |
| SQL 문 | 최신 순 · 최대 50건 |

작업 번호(#40)와 검사 번호(#0042)는 현장 기판과 기록을 맞춰볼 때 필요해서 그대로 표시합니다.

## 서버 구조와 Flask 주의사항

Flask 프로세스 하나 안에 rclpy 노드를 별도 스레드로 돌리고, 브라우저는 이 서버만 바라봅니다. 화면은 시안 HTML을 `templates/`와 `static/`으로 나눠 재사용하고, 시안용 JS(`STATES`, 로봇 애니메이션, 상태 전환 버튼)만 소켓 수신 코드로 바꿉니다.

구조: 브라우저 ↔ Flask(+SocketIO) 프로세스 [rclpy 노드 스레드 ↔ ROS 토픽] / MySQL / 스냅샷 폴더.
~~검사대 노드가 스냅샷 파일과 DB 기록을 쓰고, 서버는 읽기만 합니다.~~ → **2026-10-22 변경**: 검사 프로그램은 사진 저장 + 결과 발행만 하고, **DB에 쓰는 곳은 관제 서버 하나**입니다. 검사 프로그램 · 웹캠도 관제 PC(우분투)에서 돌립니다(별도 검사대 PC 없음).

1. **실시간 갱신은 Flask-SocketIO로** 합니다. `async_mode='threading'`을 쓰고, eventlet·gevent는 rclpy 스레드와 꼬일 수 있어 피합니다.
2. **`rclpy.spin()`은 별도 스레드**에서 돌리고, `use_reloader=False`로 두어 노드가 두 번 뜨지 않게 합니다.
3. **응답 ms는 실제 왕복 시간이 아닙니다.** `/robot/status` 마지막 수신 후 경과 시간으로 표시하고 통신 끊김 판단에도 씁니다. 예: 1초 넘으면 지연, 3초 넘으면 끊김.
4. **카메라는 MJPEG**(`multipart/x-mixed-replace`)로 보냅니다. ~~압축 토픽이 이미 JPEG라 Flask가 그대로 넘긴다~~ → **web_video_server가 MJPEG를 제공**하므로 화면이 그 주소를 직접 씁니다(위 "팀 환경 정보"). 브라우저 창마다 연결이 따로 생기므로 화면 복제로 띄웁니다.
5. **비상 정지는 twist_mux lock**으로 처리합니다. 통신이 끊기면 정지 명령이 로봇에 닿지 않으므로, `/cmd_vel`이 끊겼을 때 터틀봇이 스스로 멈추는지 실물로 시험합니다.

최소 뼈대입니다.

```python
import threading, rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from flask import Flask, render_template
from flask_socketio import SocketIO

app = Flask(__name__)
sio = SocketIO(app, async_mode="threading")

class Bridge(Node):
    def __init__(self):
        super().__init__("fms_web")
        self.create_subscription(String, "/robot/status", self.on_status, 10)
        self.lock_pub = self.create_publisher(Bool, "/cmd_vel/lock", 10)
    def on_status(self, msg):
        sio.emit("status", msg.data)

@app.route("/")
def index():
    return render_template("index.html")

@app.post("/api/estop")
def estop():
    bridge.lock_pub.publish(Bool(data=True))
    return {"ok": True}

if __name__ == "__main__":
    rclpy.init()
    bridge = Bridge()
    threading.Thread(target=rclpy.spin, args=(bridge,), daemon=True).start()
    sio.run(app, host="0.0.0.0", port=5000, use_reloader=False)
```

## 지도와 구역 좌표

**2026-10-26 실제 맵핑 지도로 교체**: 사용자가 받은 `map_test1.pgm` · `map_test1.yaml`(해상도 0.05, 144×115 px = 7.2 × 5.75 m, origin [-1.62, -1.6])을 `maps/`에 넣고 **기본 지도로 지정**(`app.py` `FMS_MAP` 기본값 `maps/map_test1.yaml`).
- 기존 샘플 지도(`maps/map.*`) · TurtleBot3 World 지도(`maps/tb3_world/`) · 두 구역 파일은 **삭제**(→ `.backup/before-map-test1_20261026_1043/`로 옮김). VS Code 실행 설정의 TurtleBot3 World 두 개 삭제, 웹캠 설정에서 지도 줄 제거. `tools/make_sample_map.py`는 남김(실행하면 `maps/map.*`를 다시 만듦).
- `config/zones.yaml`을 새 지도용으로 다시 씀. **⚠ 구역 · goal 좌표는 임시**(지도 그림만 보고 배치): 대기(왼쪽 아래) · 검사대(왼쪽 위) · 양품(오른쪽 위) · 불량(오른쪽 칸막이 사이), 마커 위치 생략, `demo_plan`도 새 지도에 맞춤. 방 안쪽 대략 x -0.4 ~ 3.8 m, y -0.4 ~ 2.3 m, 왼쪽 위 사각 장애물(x 0.3~0.9, y 1.0~1.8), 오른쪽 칸막이(y≈1.5, y≈0.6).
- **할 일**: 팀에서 실제 대기 · 검사대 · 양품 · 불량 위치와 Nav2 goal(x, y, yaw)을 받아 `zones.yaml` 수정. 로봇 AMCL이 같은 `map_test1` 파일을 쓰는지 확인.

**현재 구현 (2026-10-21)**: 지도는 파일 기반으로 바뀌었습니다. 맵핑이 끝나면 파일만 바꾸면 됩니다.
- `maps/map.yaml` + `maps/map.pgm`: 지금은 `tools/make_sample_map.py`로 만든 **샘플 지도**(3.0 × 2.0 m 작업장, 1 cm 해상도)입니다. 실제 `map_saver` 결과로 두 파일을 바꾸고 서버를 다시 켜면 됩니다.
- `fms_map.py`: 서버가 켜질 때 지도를 읽어 PNG **마스크**(벽 = 흰색, 모름 = 반투명, 빈 곳 = 투명)로 바꿔 `/map/image.png`로 제공합니다. 색은 CSS(`.map-occ`)가 테마에 맞게 입힙니다.
- `config/zones.yaml`: 구역 사각형 · 마커 위치 · 목표 자세(goal)를 **미터 단위**로 적습니다. 실제 지도에 맞게 이 값만 고칩니다.
- `static/app.js`의 `toSvg(x, y)`가 미터 → 화면 좌표 변환, `setRobotPose(x, y, yaw)`가 로봇 표시를 담당합니다. 실제 연동 때는 `/robot/status`의 x · y · yaw로 `setRobotPose`만 부르면 됩니다. 지금은 시안용으로 계획 경로를 따라 움직입니다(`placeRobot`).
- 계획 경로(`job.plan`)는 설계 지침에 토픽이 없습니다. Nav2 `/plan`을 구독할지, `/robot/status`에 담을지 확정이 필요합니다. 경로가 없으면 점선만 안 그려집니다.
- 지도 작업 전 상태는 `.backup/before-map/`에 백업되어 있습니다(git 제외).
- **지도 바꿔 켜기**: 환경변수 `FMS_MAP`(지도 yaml), `FMS_ZONES`(구역 yaml)로 고릅니다. 지정하지 않으면 `maps/map.yaml` + `config/zones.yaml`(샘플). VS Code 실행 설정에 "TurtleBot3 World 지도로 실행 (시험용)"이 있습니다.
  - `maps/tb3_world/my_map.*`: WSL `~/my_ws/src/my_bot/maps/my_map.*`(Gazebo TurtleBot3 World, 해상도 0.05)에서 복사한 시험용 실제 맵핑 지도입니다. `config/zones_tb3_world.yaml`이 짝인 시험 구역입니다(실제 작업장 값 아님).
  - 시안용 가짜 경로는 지도마다 달라서 구역 파일의 `demo_plan`에 둡니다.
- 지도가 크면(폭 5 m 초과) 격자 50 cm · 굵은 선 1 m로, 로봇 아이콘은 실제 크기(약 0.28 m)에 맞게 줄어듭니다.

시안의 지도는 자리만 잡아둔 그림이고, 2주차에 맵핑한 지도로 바뀝니다.

- **배경**: map_server의 `.pgm`을 PNG로 한 번 변환해 정적 파일로 제공합니다.
- **좌표 변환**: `.yaml`의 resolution과 origin으로 지도 좌표를 화면 픽셀로 바꿉니다. `px = (x - origin_x) / resolution`, `py = 이미지 높이 - (y - origin_y) / resolution` (y축 뒤집기에 주의).
- **작업장 크기 · 격자 표기**: 현재는 빼두었고, 실제 지도를 넣을 때 필요하면 추가합니다. 이미지 픽셀 수 × resolution으로 서버가 계산하면 됩니다.
- **구역과 마커**: 맵핑 지도에는 벽과 장애물만 나오므로, 아래 값을 설정 파일(예: `config/zones.yaml`)에 적고 화면이 지도 위에 덧그립니다. FMS가 `/fms/goal_pose`로 보내는 목표 좌표와 같은 값이므로 한 파일에서 함께 관리합니다.

| 마커 | 구역 | 설정할 값 |
|---|---|---|
| 0 | 대기 (주차 · 복귀) | 구역 사각형, 목표 좌표(마커 앞 20~30 cm) |
| 1 | 검사대 (적재) | 같음 |
| 2 | 양품 | 같음 |
| 3 | 불량 | 같음 |
| 4 | 폐기 (추후 확장) | 3분류로 확장할 때 추가 |

## DB

**현재 구현 = 설계 2안 (2026-10-22 오후, 팀원 설계 계획 + 답변 반영)**. 아래 "1안" 내용은 기록용이고, 코드는 2안 기준입니다.
- 테이블 3개 (`db/schema.sql`, PK 이름은 `명칭_id`):
  - `inspection`: inspection_id · result(**PASS/FAIL**) · inspected_at · `esp01_status` · `ic_chip_status` · `fnd_status` · `switch_status`(검사 프로그램 결과 코드 문자열 그대로: `PASS`, `MISSING`, `OFFSET(14.2px)`, `TILT(+4.5d)`, 여러 개면 쉼표) · img_path. **부저는 빼기로 함.** 판정 방식 · 상자 사진 컬럼 없음(상자는 실시간 검출 영상으로만 봄).
  - `delivery`: delivery_id · inspection_id(UNIQUE) · dest_marker · called_at(NOT NULL) · station_arrived_at · departed_at · return_started_at · total_sec(= 대기소 복귀 시작 − 호출). 이송 중인지 같은 상태 컬럼은 없음(로봇 상태 변수로 관리).
  - `event`: event_id · delivery_id(NULL 허용) · event_type(`OBSTACLE_STOP` 3초 안에 풀림 / `REROUTE` 경로 재탐색 / `COMM_LOST` / `ESTOP`) · occurred_at · x · y · resumed_at(재출발 · 복구 · 해제).
- **재촬영 = 새 검사 줄**(새 검사 번호, 이전 검사는 남음). 아직 하역장으로 출발 전인 주행은 새 검사로 연결을 옮기고 목적지를 새 판정에 맞춤. 출발한 기판은 재촬영 거절(409, 화면에 알림).
- **오늘 요약**: 주행으로 이어진 검사(= 기판별 최종 검사)만 셈 → "PASS ○○%". 평균 이송 = 오늘 대기소 복귀 시작한 주행의 total_sec 평균.
- **이벤트 기록 창**: 세 테이블을 시간순으로 합쳐 보여 줌(검사 1줄, 주행은 호출 · 검사대 도착 · 출발 · 복귀 시작 4줄, 이벤트 1줄). 문구는 DB에 저장하지 않고 `store.py`의 `timeline()`이 만듦. 분류: 검사 / 주행 / 안전(장애물 · 재탐색 · 비상 정지) / 통신.
- 화면: 판정 표기 PASS/FAIL, 검사 결과 칸의 "판정 방식" 줄 → **"부품 상태"**(부품 4개 초록/빨강). img_path가 `logs/img_0001.jpg`처럼 하위 폴더여도 `/snapshots/` 아래에서 찾음(`FMS_SNAPSHOT_DIR`를 검사 프로그램 폴더로 지정하면 됨).
- 시안 연결: 상태 전환 "보행자 감지" → `OBSTACLE_STOP` 열기/닫기, "통신 끊김" → `COMM_LOST`, 비상 정지 · 해제 → `ESTOP` 열기/닫기. "검사대에 기판 올리기" → PASS 검사 + 주행 호출 1건.
- **1안으로 DB를 이미 만든 PC**: root로 `db/drop_v1.sql`(옛 테이블 삭제) → `schema.sql` → `seed.sql`. 서버는 2안 테이블이 없으면 이 순서를 안내하며 멈춤. 계정 `fms_app` 권한은 그대로 사용 가능.
- 검증: 메모리 모드 + 임시 MySQL(포트 3307, 끝나고 삭제)에서 같은 결과 확인. 작업 전 백업: `.backup/before-db-v2_20261022_1228/`.
- 남은 확인: 보행자 정지를 `OBSTACLE_STOP`과 따로 둘지, 이벤트 종류 4개로 충분한지(팀원).

**1안 (2026-10-22 오전, 지금은 안 씀)**: 설계서 초안을 아래 5개 테이블로 바꿨던 내용입니다.
- `db/schema.sql`: 테이블 생성 (MySQL 8.0, DB 이름 `fms`, utf8mb4). 여러 번 실행해도 안전.
- `db/seed.sql`: 예시 데이터 (실행한 날짜 기준 시각, **기존 데이터를 지움** — 개발 PC 전용).
- `db/create_user.sql`: 관제 서버 전용 계정 `fms_app` (SELECT/INSERT/UPDATE/DELETE만). 비밀번호는 사용자가 정해 `.env`에 적음 (`.env.example` 참고, `.env`는 git 제외). **계정 비밀번호는 Claude가 다루지 않습니다.**
- `db/check_db.py`: `.env`로 접속해 건수 · 오늘 요약 · 최근 6건 출력.
- 테이블: `inspection`(기판 1장, 최종 판정 = 마지막 촬영) · `inspection_shot`(촬영 1회, 재촬영 기록 보존, 사진 두 장 파일 이름) · `inspection_defect`(부품별 불량: part / type / value) · `delivery`(이송 작업, 단계별 시각 · total_sec) · `event`(안전 · 통신 · 비상 정지 · 검사 · 배송을 한 테이블로, 이벤트 기록 창은 이것만 읽음).
- 사진은 DB에 파일 이름만 저장. 이름 규칙: `{YYYYMMDD}_{HHMMSS}_{검사번호 4자리}_s{촬영번호}.jpg` (+ `_box.jpg`).
- 부품 · 불량의 한글 이름은 DB가 아니라 서버 코드의 대응표에 둡니다.
- DB 위치: 개발 중에는 개발 PC(Windows)의 MySQL 8.0, 통합 때 관제 PC(Ubuntu)에 `mysql-server`를 설치하고 같은 SQL을 실행. 관제 서버가 DB에 쓰는 유일한 곳 (검사대 프로그램은 `/vision/result` 발행과 사진 저장만).
- **서버 연결 (2026-10-22)**: `store.py`가 저장소를 고릅니다. `.env`에 `FMS_DB_PASSWORD`가 있으면 **MySQL**, 없으면 **메모리 가짜 데이터**(`seed.sql`과 같은 내용). `FMS_STORE=memory|mysql`로 강제 가능. MySQL로 정했는데 접속이 안 되면 서버가 오류를 내고 멈춥니다(조용히 가짜 데이터로 바뀌지 않음). 켤 때 터미널에 ` * 데이터: ...`로 어느 쪽인지 표시.
  - DB에서 읽는 것: 최신 검사(최종 촬영 · 불량 목록 · 목적지), 최근 6건, 오늘 요약, 이벤트 기록(날짜 · 종류 필터, 최신 50건).
  - DB에 쓰는 것: 재촬영(촬영 줄 추가 + 판정 갱신 + RETAKE/INSPECTED 이벤트), 시안용 가짜 검사, 비상 정지 작동 · 해제(ESTOP_ON/OFF), 시안용 상태 전환(PERSON_STOP / COMM_LOST).
  - 로봇 위치 · 상태 · 비상 정지 여부 · 현재 작업(job)은 DB가 아니라 `app.py` 메모리 (실시간 값).
  - 예시 데이터 시각은 서버를 켠(또는 `seed.sql`을 실행한) 직전 15분으로 잡혀, 새 기록이 항상 맨 위에 쌓입니다.
  - 작업 전 상태 백업: `.backup/before-db-read_20261022_0914/`
- 미정: 검사 번호를 누가 매길지 (DB AUTO_INCREMENT로 서버가 매기는 안 vs 검사대가 매기는 안). 사진 이름에 검사 번호가 들어가서 검사대 담당과 정해야 함.

아래는 처음 인수인계 문서의 초안입니다(참고용).

MySQL을 쓰고, 설계서 초안의 세 테이블에서 시작합니다. 메인 화면은 DB를 계속 조회하지 않고, 아래 시점에만 읽습니다.

| 테이블 | 주요 컬럼 |
|---|---|
| inspection | id · inspected_at · result(OK/NG) · defect_type · method(CV/AI) · image_path |
| delivery | id · inspection_id · dest_marker · called_at · docked_at · loaded_at · arrived_at · unloaded_at · total_sec · status |
| safety_event | id · delivery_id · occurred_at · kind(person/obstacle) · x · y · action(wait/reroute) |

| 화면 | 조회 시점 | 내용 |
|---|---|---|
| 오늘 요약 | 페이지를 열 때, 배송이 끝날 때 | 오늘 검사 수, OK 비율, 평균 total_sec |
| 최근 검사 6건 | 새 검사 결과가 올 때 | inspection 최신 6건 |
| 이벤트 기록 창 | 창을 열 때, 조회를 누를 때 | 세 테이블을 시간순으로 합쳐 `ORDER BY 시각 DESC LIMIT 50`, 날짜 · 종류 필터 |

- 이벤트 기록은 메인 화면에 띄우지 않고 `/events` 별도 페이지로 새 창에 엽니다.
- 통신 지연 · 끊김도 기록에 남기려면 테이블이 하나 더 필요합니다(예: comm_event). 확정 필요 항목입니다.
- 시간 컬럼(occurred_at, inspected_at, called_at)에 인덱스를 두어 날짜 조회를 빠르게 합니다.
- 사진은 DB에 경로만 저장하고, 파일은 스냅샷 폴더에서 제공합니다.

## 결정 사항 · 진행 중인 계획 (2026-10-22)

### 확정한 것
- **관제 PC 구성**: 관제 서버(Flask + 나중에 rclpy) · MySQL · 검사 프로그램(웹캠) · 영상 서버를 모두 관제 PC(Ubuntu 22.04)에 둡니다. 관제 PC에는 **MySQL 서버만** 설치(`sudo apt install mysql-server`), 워크벤치는 선택. 개발 중 DB는 개발 PC(Windows)의 MySQL 8.0.45(서비스 `MySQL80`, 워크벤치 8.0 있음). 사용자가 워크벤치에서 `fms` DB를 만들고 2안 테이블 3개로 바꿔 둠(2026-10-23 화면으로 확인, 데이터는 비어 있음). `.env` 만들어 MySQL 모드로 동작 확인(2026-10-23, 웹캠 검사 #0001 저장됨).
- **DB 구조**: ~~5개 테이블(1안)~~ → 오후에 **팀원 설계 기준 2안(테이블 3개)으로 변경**. 위 "DB" 절 참고.
- **이벤트 기록 버튼 유지**: DB에 쌓이는 것과 작업자가 보는 것은 별개. 관제 PC에서 SQL 없이 확인하는 유일한 방법.
- **`.env`는 DB를 쓸 때만** 필요(없으면 메모리 모드). 비밀번호는 `.env`에만, `launch.json`에 넣지 않음(git에 올라감).

### 검사대 코드 리뷰 결과 (팀원 `webcam/pcb_cv_inspector3.py`, 팀원 파일이라 수정 안 함)
- **높음 (판정 오류)**
  1. `measure_component_tilt()`가 측정 실패(`NO_CONTOUR`, `AREA_TOO_SMALL`)를 돌려주면 호출부가 `TILT(+0.0d)` 불량으로 기록 → 0도인데 기울어짐 NG.
  2. `inspect_buzzer_shape()`의 `FAIL_MISSING`이 호출부에서 `SHAPE(0.00)`으로 기록 → 부저 누락이 "모양 불량"으로 나감.
  3. 기판 모서리를 못 찾으면 화면 전체를 늘려서 검사 진행(`warp_and_normalize` else) → 의미 없는 판정. "기판 미검출"로 멈춰야 함(재촬영 대상).
  4. `best.pt`가 없으면 고정 위치 모드로 조용히 전환 → 누락(MISSING)을 거의 못 잡음. 모델 경로가 현재 폴더 기준.
- **중간**: 기판을 90도 돌려 놓으면 펴기가 틀어짐(긴 변 세로 정렬 없음) · 기울기 공식이 세로로 긴 부품만 가정 · 밝기 기준 `85` 고정.
- **낮음**: `MIN_CIRCULARITY 0.80` 미사용(실제는 `0.88`) · 부품 이름표 고정(`model.names` 권장) · 화면 뒤집기 `flip(-1)` · 카메라 0번 고정.
- **연결 준비**: 불량을 문자열(`"OFFSET(13.9px)"`)이 아니라 `{"part","type","value"}`로도 남기기 · 상자 없는 사진(`clean_img`)과 상자 그린 사진을 검사마다 따로 저장(지금은 `latest_inspection_result.jpg` 하나에 덮어씀) · `PASS/FAIL` → `OK/NG`.
- 팀원에게 전달할 리뷰 문서나 수정본은 아직 안 만듦(사용자 요청 시).

### 웹캠 사진 → 스냅샷 연결 (2026-10-22 완료, HTTP 임시 연결)
- **실제 구현**(아래 "원래 계획"과 다름: 서버가 이름을 바꾸지 않고, 팀원 프로그램의 경로를 그대로 씀):
  - `store.py` `record_result(result, inspected_at, statuses, img_path)` (메모리 · MySQL): 검사 1줄 + 주행(호출) 1줄, 목적지 PASS→2 / FAIL→3.
  - `app.py` `POST /api/inspections`: 팀원 `db_record`(`final_decision` 또는 `result`, `inspected_at` `YYYY-MM-DD HH:MM:SS`, 부품 상태 4개, `img_path`)를 받음. 사진 폴더 안의 실제 파일만 허용(폴더 밖 · 없는 파일 400). 사용자가 직접 작성.
  - `tools/run_inspector_with_fms.py`: 팀원 파일을 고치지 않고 불러와 `execute_inspection_sequence`를 감싸서 비어 있는 `db_manager` 자리에 `FmsSender`(HTTP POST)를 넣고 실행. webcam 폴더로 `cd` 한 뒤 `py -3.10 C:\Users\302-2\Desktop\fmsUI\tools\run_inspector_with_fms.py`. 팀원 이름 세 가지(`pcb_cv_inspector3_2`, `execute_inspection_sequence`, `insert_inspection_result`)에 의존.
  - 사용자가 직접 촬영 → 관제 화면 표시까지 확인(2026-10-22).
  - 나중에 `/vision/result` 토픽으로 바꾸면 이 실행 파일은 삭제하고, 서버의 확인 · 저장 코드(함수로 빼 둘 것)와 `record_result`, 화면은 그대로 씀.
  - ~~남은 보완: 500 → 400~~ → 2026-10-26 `save_inspection_result()` 분리하며 해결.
- 팀원 확인 요청 중(답 대기): DB는 관제 서버만 쓰기 · 로봇 호출 주체 · 저장 사진 종류(상자 그린 사진만) · logs 위치 · 재촬영 요청 방법 · `final_decision` 키 이름 · 기울기 측정 실패를 TILT로 기록하는 문제 · best.pt 경로 · 시리얼 COM3.

#### 원래 계획 (A 방식, 기록용)
- 목적: 개발 PC에 웹캠을 꽂고 찍은 사진이 관제 화면 스냅샷 칸과 DB에 들어가는지 확인. 판정은 하지 않음(2단계에서 팀원 YOLO 판정을 붙임). 현재 개발 PC에 웹캠 미연결, Python 3.14에 `cv2`는 있고 `ultralytics`/`torch`는 없음.
- 계획:
  1. `store.py`에 `record_result(payload)` (메모리 · MySQL 둘 다). 나중에 `/vision/result` 토픽 구독도 같은 함수를 부름.
  2. `app.py`에 `POST /api/inspections` (결과 받는 창구). **검사 번호와 사진 이름은 서버가 정함**: 검사 프로그램은 `snapshots/`에 아무 이름(예: `incoming_*.jpg`)으로 저장해 보내고, 서버가 규칙 이름(`{YYYYMMDD}_{HHMMSS}_{번호4}_s{촬영}.jpg`)으로 바꿈. `snapshots` 안의 실제 파일만, 폴더 밖 경로는 거절.
  3. `tools/capture_to_fms.py`: 웹캠 창, 스페이스 = 찍어서 전송, Q = 종료. 서버 주소 · 카메라 번호 · 뒤집기 옵션.
  4. ~~판정 방식 "미판정" 표시~~ → 2안에는 판정 방식 컬럼이 없음. 1단계 시험 사진은 부품 상태를 모두 `PASS`, result `PASS`로 저장(오늘 PASS 비율에 섞임 → 시험 후 `seed.sql`로 초기화). 표시 방법은 착수 때 다시 정함.
  5. ~~상자 사진 대신 표시~~ → 2안에서 검사 화면은 이미 img_path 사진을 보여 줌.
  6. 결과 JSON 형식(2안 기준으로 갱신, 나중 `/vision/result`와 동일하게 팀원과 확정): `{"result":"PASS","esp01_status":"PASS","ic_chip_status":"PASS","fnd_status":"PASS","switch_status":"PASS","img_path":"incoming_....jpg"}`
- 우분투로 옮기면 HTTP 창구 대신 ROS 구독만 붙이면 됨(저장 함수 · 화면은 그대로, 시험용 촬영 스크립트만 버림).

### 배터리 · 통신 표시 준비 (2026-10-23, ROS 없이 완료)
- 화면의 배터리 78% · "응답 ○○ ms"는 가짜 고정값이었음 → 서버 값으로 바꿈. 사용자가 단계별로 작성하고 Claude가 체크(1-2는 Claude 작성).
- `app.py`: 기준값 `COMM_DELAY_SEC=1.0` · `COMM_LOST_SEC=3.0` · `BATT_FULL_V=12.6` · `BATT_EMPTY_V=10.5` · `BATT_LOW_PCT=25`. `robot`에 `last_seen` · `battery` · `comm_lost`(2026-10-29 삭제, 통신 끊김 DB 기록을 뺌).
  - `battery_percent(percentage, voltage)`: percentage(0~1 또는 0~100) 우선, 비었거나 0 · NaN이면 전압으로 계산.
  - `update_robot(percentage, voltage)`: 무언가 받을 때마다 부름(마지막 수신 시각 + 배터리). **나중에 rclpy 콜백이 부를 함수.**
  - `robot_link()`: none / ok(1초 이내) / delay(1~3초) / lost(3초 넘음) 판단, 끊김 · 복구 때만 `COMM_LOST` 이벤트 열기 · 닫기. 지금은 `/api/status` 요청 때만 판단 → ROS 연결 때 1초 타이머로.
  - `snapshot()`에 `"robot": robot_link()`.
  - **`POST /api/robot`(개발용, ROS 연동 때 삭제)**: `{"percentage": 0.76}` / `{"voltage": 11.9}` / `{}`(수신만).
- `index.html`: 통신 처음 표시 "수신 없음"(회색), 배터리 `-`. `app.js`: `showLink()` · `linkAge()`, `applyStatus`가 실제 끊김이면 시안 '통신 끊김' 화면(배너 · 흐림) 사용, `tick()`의 가짜 응답 ms 삭제. `style.css`: `.lamp.warn` · `.lamp.idle` · `.batt span.low`.
- 확인: 메모리 모드 브라우저에서 수신 없음 → 연결됨 → 끊김(배너 · 무응답 시간) → 복구, 배터리 67% · 20%(빨강) · 색 모두 확인.
- **설계 지침(인수인계 문서) 기준**: 통신 판단은 `/robot/status` 수신 간격, 로봇 위치(x · y · yaw)도 `/robot/status` JSON. 배터리는 `/battery_state`. → `/robot/status` 형식을 팀에 확인 요청 필요(지도 좌표 x · y(m) · yaw(rad) · 상태 이름 · 발행 주기). 로봇 위치 표시는 맵핑 지도 적용 뒤 마지막 단계로(로봇 AMCL과 같은 지도 파일 필수).
- ROS 연동 때: `ros_bridge.py`(토픽 이름 · 콜백 → `update_robot`), `/api/robot` 삭제, `robot_link()` 1초 타이머, `use_reloader=False`.
- 백업: `.backup/before-robot-link_20261023_1056/`. Claude 확인용 `.claude/launch.json`에 `fms-test-mem`(메모리 모드, 5004) 추가.

### ROS 토픽 받기 (2026-10-26, 1~3단계 구현 · WSL 시험 통과)
- **`ros_bridge.py`(새 파일)**: 토픽 이름 · 도메인 번호를 맨 위 한곳에 둠. `DOMAIN_ID = "22"`(환경변수 `ROS_DOMAIN_ID`가 있으면 그 값 우선, `rclpy.init()` 전에 설정). rclpy가 없으면 `start()`가 `None` → Windows에서는 ROS 없이 그대로 동작.
  - 구독: `/robot/status`(String, 받으면 통신 살아 있음 → `update_robot()`, JSON 내용은 형식 확정 후) · `/battery_state`(BatteryState, `qos_profile_sensor_data` → `update_robot(percentage, voltage)`) · `/vision/result`(String JSON → `save_inspection_result()`, 거절 시 경고 로그).
  - 발행: `/cmd_vel/lock`(Bool) — 비상 정지 `True`, 해제 `False`.
  - 1초 타이머 → `robot_link()`(화면을 안 열어도 끊김 판단 · 기록).
  - `app.py`가 `handlers` dict로 함수를 넘김(서로 import 꼬임 방지).
- **`app.py`**: `save_inspection_result(rec)` 분리(ValueError → HTTP는 400, 토픽은 로그. dict 아님 · img_path 문자열 아님 · 시각 숫자도 400 — 예전 500 문제 해결). `/api/inspections`는 이 함수를 부르기만 함. 비상 정지 · 해제에서 `BRIDGE.publish_estop()`. 파일 끝에서 `FMS_ROS=1`일 때만 `ros_bridge.start()` → 터미널에 ` * ROS: 연결됨 · ROS_DOMAIN_ID=22`.
- **실행 (우분투 / WSL)**: `source /opt/ros/humble/setup.bash` 후 `FMS_ROS=1 FMS_SNAPSHOT_DIR=<webcam 폴더> python3 -m flask --app app run --host 0.0.0.0 --port 5000 --no-reload` (`--no-reload` 필수: 노드 두 번 뜸 방지).
- **WSL 시험 결과**(Ubuntu-22.04, ROS Humble, Python 3.10, 메모리 모드, 가짜 토픽은 `ROS_DOMAIN_ID=22`): 수신 없음 → `/robot/status` 받으면 ok → 5초 무응답 lost → `/battery_state` 11.9 V → 67% → `/vision/result` → 검사 #0044 PASS 저장 · 사진 경로 → 잘못된 JSON은 거절 로그 → 비상 정지 · 해제 시 `/cmd_vel/lock` `true` / `false` 확인. WSL에 서버 패키지 설치함(`python3 -m pip install --user -r requirements.txt`).
- 남은 것: `/robot/status` JSON에서 위치 · 상태 꺼내기(형식 확정 후), 재촬영 요청 토픽, 비상 정지 실패 표시, 실물 터틀봇 확인 후 `/api/robot` 삭제. 백업: `.backup/before-ros-bridge_20261026_0911/`.

### 아직 팀과 정할 것 (DB 관련 추가분)
- 로봇 상태 단계가 확정되면 `delivery`의 단계별 시각 컬럼을 맞출 것.
- 로봇이 2대 이상이 될 가능성이 있으면 `delivery` · `event`에 로봇 번호 컬럼 추가(지금은 없음).
- 통신 이벤트는 상태가 바뀔 때만 기록(1초마다 쌓이지 않게) — ROS 연결 때 구현.
- 이벤트 `message`를 한글 문장으로 저장 중(문구를 바꾸면 예전 기록은 예전 문구). `code`도 함께 저장하므로 나중에 보여 줄 때 만드는 방식으로 바꿀 수 있음.
- 관제 서버 코드 리뷰: ~~비상 정지 실패 시 표시 없음~~ · ~~지도 yaml 오류 시 서버가 안 켜짐~~ → **2026-10-26 해결**(비상 정지 · 해제 요청 실패 시 경고창, 지도 · 구역 파일이 깨져도 서버는 켜지고 터미널에 `[!]` 표시 · 화면은 "지도 파일 없음"). 남은 것: `render()` 안의 변수 `S` 이름 겹침(동작 문제 없음), 서버가 `/cmd_vel/lock`을 보냈지만 로봇까지 갔는지는 모름(통신 끊김 배너로만 판단). `.env.example`에 우분투용 `FMS_SNAPSHOT_DIR` · `FMS_ROS` · `FMS_MAP` · `FMS_ZONES` 예시 추가. 백업 `.backup/before-premove-fix_20261026_1054/`.

> 관제 PC(우분투)로 옮기는 순서와 옮긴 뒤 작업은 **`UBUNTU_SETUP.md`**에 따로 정리 (2026-10-26).

## ROS 연동 때 정리 목록 (2026-10-29 갱신)

**지울 것 (시안 · 개발용)**
- [ ] `POST /api/robot` (`app.py`) — 가짜 배터리 · `/fms/status` 흉내 입구 (실물 확인 뒤)
- [x] ~~`tools/run_inspector_with_fms.py`~~ (2026-10-27 삭제, 검사 저장은 main.py → db_manager)
- [x] ~~시안 상태 전환 · 검사대 시뮬레이션 버튼, `/api/state` · `/api/inspections/simulate` · `STATE_EVENT`~~ (2026-10-27). store.py 쪽 시안 · 쓰기 함수도 2026-10-29 삭제. 남은 것: 미리보기 줄(발표 모드 버튼은 남길지 결정)
- [x] ~~재촬영 버튼 · `/api/inspections/retake`~~ (2026-10-27)
- [x] ~~비상 정지 버튼 · `/api/estop` · `/cmd_vel/lock` 발행~~ (2026-10-29)
- [ ] 지도 시안 애니메이션: `placeRobot()` · `frame()`의 `progress`, `job`의 고정값(`id: 40`, `dest_marker: 3`, `demo_plan`) — `/fms/status`를 받으면 이미 멈추지만 코드는 남아 있음
- [ ] `STATES`의 `timerFrom`(가짜 경과 시간) · 시안용 사람 아이콘 위치

**가짜 값 → 실제 값 (main.py `/fms/status`)**
- [x] 상태 배지 · 지도 로봇 위치 · 속도 · 배터리 (2026-10-28, `showFms()`) — 실물 확인 남음
- [ ] A\* 상태 이름 전체를 `MISSIONS`에 (지금 6개, 2026-10-29)
- [ ] 위치 인식 `정상` · 남은 거리 · 계획 경로 · 목적지 · 작업 번호 — main.py가 보내 주면
- [ ] 카메라 위 `전방 감지 없음/사람 감지` · 안전 정지 화면 — main.py가 보내 주면 (`front_dist`는 서버에 저장만)
- [ ] 통신 판단: 지금은 `/fms/status` 수신 간격(= main.py 생존). main.py가 `robot.last_seen`을 주면 터틀봇 기준으로

**관제 PC(우분투) 환경** → `UBUNTU_SETUP.md`
- [ ] `ROS_DOMAIN_ID=22`, `~/turtlebot_vision_amr/fms_ui` + `fms_manager`, 로컬 MySQL, `.env` 두 곳, main.py 시리얼 `/dev/ttyACM0` · 9600 · 모델 `fms_manager/weights/best.pt` 확인(팀원 파일)
- [ ] 카메라 주소(`index.html`의 `192.168.0.42:8080`): 영상 서버를 관제 PC에서 돌리면 그 주소로

## 작업 순서

가짜 데이터로 화면과 서버를 먼저 잇고, 실제 토픽은 하나씩 교체합니다.

- [x] 저장소에 `CLAUDE.md`(이 문서) 넣기 — 시안 `fms-console.html`은 아직 저장소에 없음
- [ ] 상태 이름 · 메시지 형식 · DB 테이블 확정 (서버 착수 전 확정할 것 참고)
- [x] 시안을 `templates/index.html` + `static/`(CSS · JS)로 나누기
- [ ] 가짜 데이터 스레드로 Flask-SocketIO 연결 확인 (ROS 없이) — 현재는 폴링 방식
- [x] MySQL 테이블 생성 SQL과 예시 데이터 (`db/`), 서버가 DB 읽고 쓰기 (`store.py`) — 2026-10-22, 같은 날 오후 팀원 설계 2안(테이블 3개)으로 교체
- [ ] `/events` 별도 페이지 (지금은 모달 창, 버튼은 유지)
- [x] 웹캠 사진 → 스냅샷 연결 (팀원 YOLO 판정 포함, HTTP 임시 연결 `tools/run_inspector_with_fms.py`) — 2026-10-22. 다음: `/vision/result` 토픽으로 교체
- [x] `ros2 topic pub`으로 가짜 `/robot/status` · `/vision/result`를 보내 rclpy 연결 확인 — 2026-10-26 WSL에서 확인(`/battery_state`, `/cmd_vel/lock` 포함)
- [x] 전방 카메라: web_video_server MJPEG 주소를 카메라 칸 `<img>`에 연결 + 끊김 시 "영상 신호 없음"(5초마다 재연결) — 2026-10-22 관제 화면에서 터틀봇 영상 확인 (압축 옵션 제외)
- [ ] 비상 정지 → `/cmd_vel/lock` 발행, 해제 확인 흐름
- [x] 통신 끊김 판단(마지막 수신 후 경과 시간)과 화면 전환 — 2026-10-23 서버 · 화면 완료(개발용 `/api/robot`으로 확인). 남은 것: ROS 콜백 연결
- [ ] 맵핑 지도 PNG 변환과 `config/zones.yaml` 덧그리기 — 2026-10-26 실제 지도 `map_test1` 적용 완료. **실제 구역 · goal 좌표 입력만 남음**(지금은 임시 값)
- [ ] 실물 터틀봇으로 통합 확인: 배터리 %, 완전 통신 끊김 시 정지 여부
