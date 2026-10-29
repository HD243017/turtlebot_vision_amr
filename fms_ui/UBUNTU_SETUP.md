# 관제 PC(우분투)로 옮기기 · 이후 작업 정리

> 작성 2026-10-26, **2026-10-29 구조 변경 · 협업 저장소 폴더 구성 · DB 읽기 (나) 방식 반영**. 개발 PC(Windows)에서 만든 관제 화면 서버를 관제 PC(Ubuntu 22.04 + ROS 2 Humble)로 옮겨 실행하는 순서입니다.
> 자세한 배경과 결정 내용은 `CLAUDE.md`를 봅니다.

## 한눈에 보기

관제 PC 한 대에 아래를 모두 둡니다. 팀 협업 저장소(`HD243017/turtlebot_vision_amr`) 하나를 받으면 두 폴더가 같이 옵니다.

```
~/turtlebot_vision_amr/
├─ fms_manager/          ← 팀원 (main.py 쪽)
│  ├─ main.py
│  ├─ pcb_cv_inspector3_2.py
│  ├─ db_manager.py      ← 우리 (DB 쓰기 함수)
│  ├─ weights/best.pt
│  ├─ .env               ← DB 다섯 줄 (git 제외)
│  └─ logs/pass · fail/  ← 검사 사진이 쌓이는 곳
└─ fms_ui/               ← 우리 (관제 화면 서버 = 이 폴더)
   ├─ app.py · store.py · ros_bridge.py · fms_map.py
   ├─ templates/ · static/ · db/ · config/ · maps/
   └─ .env               ← DB + FMS_SNAPSHOT_DIR · FMS_ROS (git 제외)
```

| 무엇 | 위치 | 담당 | 비고 |
|---|---|---|---|
| 관제 화면 서버 (Flask + rclpy) | `~/turtlebot_vision_amr/fms_ui` | UI · DB | **보기 전용** (로봇으로 보내는 토픽 없음). DB는 `store.py`로 직접 읽기만 ((나) 방식) |
| main.py + 검사 프로그램 | `~/turtlebot_vision_amr/fms_manager` | 팀원 | `main.py`, `pcb_cv_inspector3_2.py`, `weights/best.pt` + 우리 `db_manager.py` |
| MySQL | 관제 PC 로컬 (`127.0.0.1`) | UI · DB | 개발 PC의 DB와는 별개 (데이터는 옮겨지지 않음) |
| 영상 서버 (web_video_server) | 지금은 리눅스 PC `192.168.0.42` | 팀원 | 관제 PC로 옮기면 화면 주소 변경 (8단계) |

데이터 흐름:
```
터틀봇 · A* ◀─토픽─▶ main.py ──/fms/status──▶ 관제 화면 서버 ──▶ 브라우저
                      │                         │
                      └─ db_manager.py ─▶ MySQL ◀┘ (화면 서버는 읽기만)
검사 사진: ~/turtlebot_vision_amr/fms_manager/logs/...  ──▶ 화면 서버가 직접 읽어 스냅샷 칸에 표시
터틀봇 카메라: web_video_server MJPEG ──▶ 브라우저가 직접 표시
```

- 비상 정지 · 적재 완료 · 하역 완료는 **main.py 창의 키**(R · L · U)로 합니다. 관제 화면에는 버튼이 없습니다.
- main.py는 2026-10-29 팀원 커밋 기준 (`/fms/status` 0.5초 발행, 시리얼 `/dev/ttyACM0` · 9600, 모델 `main.py 옆 weights/best.pt`, L · U 키는 로봇 상태 확인 후 명령)
- 검사 프로그램은 사진 경로를 **절대 경로**로 DB에 넣습니다. 관제 화면이 `FMS_SNAPSHOT_DIR` 기준으로 바꿔 보여 주므로 그대로 둡니다.
- ROS 도메인 번호: **22**
- 지도: **`maps/map_test1.yaml`** (기본값. 구역 좌표는 아직 임시)

---

## 0. 옮기기 전 (개발 PC)

- [ ] 협업 저장소에 올리기: 브랜치 `feature/fms-ui`에 이 폴더 내용을 `fms_ui/`로, `db_manager.py`를 `fms_manager/`에 넣고 PR → 병합
- [ ] **`.env` · `.backup/` · `.vscode/` · `.claude/`는 올리지 않습니다** (`.env`에 개발 PC DB 비밀번호). 우분투에서 `.env`를 새로 만듭니다
- [ ] `best.pt`가 저장소에 없으면(용량) 따로 받아 둡니다 → 1단계에서 `fms_manager/weights/`에 넣음

## 1. 파일 놓기

```bash
cd ~ && git clone https://github.com/HD243017/turtlebot_vision_amr.git
```
PR이 아직 병합 전이면 `cd ~/turtlebot_vision_amr && git checkout feature/fms-ui`.

확인: 두 폴더와 모델 파일이 있어야 합니다.
```bash
ls ~/turtlebot_vision_amr/fms_manager ~/turtlebot_vision_amr/fms_ui ~/turtlebot_vision_amr/fms_manager/weights
```
`weights/best.pt`가 없으면 `mkdir -p ~/turtlebot_vision_amr/fms_manager/weights` 후 받아 둔 `best.pt`를 그 안에 복사합니다.

## 2. ROS 환경 · 도메인 번호 22

터미널을 열 때마다 자동 적용되게 `~/.bashrc`에 넣습니다 (한 번만).
```bash
echo 'source /opt/ros/humble/setup.bash' >> ~/.bashrc && echo 'export ROS_DOMAIN_ID=22' >> ~/.bashrc && source ~/.bashrc
```

## 3. 패키지 설치

관제 화면 서버:
```bash
cd ~/turtlebot_vision_amr/fms_ui && python3 -m pip install --user -r requirements.txt
```
main.py · 검사 프로그램 (팀원이 이미 설치했으면 생략):
```bash
python3 -m pip install --user ultralytics pyserial
```
- 가상환경을 쓰려면 반드시 `python3 -m venv --system-site-packages .venv` (rclpy가 보이도록)

## 4. MySQL 설치 · DB 만들기

```bash
sudo apt update && sudo apt install -y mysql-server
```
```bash
cd ~/turtlebot_vision_amr/fms_ui && sudo mysql < db/schema.sql
```
관제용 계정 만들기 — 비밀번호가 파일에 남지 않게 직접 입력합니다.
```bash
sudo mysql
```
```sql
CREATE USER 'fms_app'@'localhost' IDENTIFIED BY '새비밀번호';
GRANT SELECT, INSERT, UPDATE, DELETE ON fms.* TO 'fms_app'@'localhost';
exit
```
- 비밀번호는 영문 · 숫자 · 기호 섞어 8자 이상. 채팅 · 캡처에 남기지 않기
- MySQL Workbench는 설치하지 않아도 됩니다 (데이터 확인은 6단계 `check_db.py` 또는 `sudo mysql`)
- `db/drop_v1.sql`, `db/seed.sql`은 쓰지 않음 (seed는 예시 데이터)

## 5. `.env` 두 곳 만들기

```bash
cd ~/turtlebot_vision_amr/fms_ui && cp .env.example .env && nano .env
```
`.env.example`이 이미 아래 모양이라 **비밀번호와 `사용자이름`만** 고치면 됩니다 (`whoami`로 확인). 최종 모양:
```
FMS_DB_HOST=127.0.0.1
FMS_DB_PORT=3306
FMS_DB_NAME=fms
FMS_DB_USER=fms_app
FMS_DB_PASSWORD=4단계에서정한비밀번호
FMS_SNAPSHOT_DIR=/home/사용자이름/turtlebot_vision_amr/fms_manager
FMS_ROS=1
```
- 저장: Ctrl+O → Enter → Ctrl+X
- `FMS_SNAPSHOT_DIR`은 main.py 폴더입니다. 검사 사진이 `fms_manager/logs/...`에 쌓이고 DB에는 절대 경로가 들어가는데, 관제 화면이 이 폴더 기준으로 바꿔 보여 줍니다(이 폴더 밖 사진은 "사진 없음")
- (나) 방식이라 관제 화면 서버도 DB 접속 정보가 필요합니다. 그래서 `.env`가 두 곳입니다

`db_manager.py`는 **자기 옆의 `.env`**를 읽으므로 main.py 폴더에도 복사합니다 (DB 줄만 쓰고 나머지는 무시).
```bash
cp ~/turtlebot_vision_amr/fms_ui/.env ~/turtlebot_vision_amr/fms_manager/.env
```

## 6. DB 접속 확인

```bash
cd ~/turtlebot_vision_amr/fms_ui && python3 db/check_db.py
```
"접속 성공"이 나오면 됩니다. 처음에는 건수가 모두 0입니다.

## 7. 실행 (터미널 2개)

관제 화면 서버:
```bash
cd ~/turtlebot_vision_amr/fms_ui && python3 -m flask --app app run --host 0.0.0.0 --port 5000 --no-reload
```
아래 세 줄이 나오면 준비 완료:
```
 * 지도: maps/map_test1.yaml · 구역: zones.yaml
 * 데이터: MySQL fms_app@127.0.0.1:3306/fms
 * ROS: 연결됨 · ROS_DOMAIN_ID=22
```
- `--no-reload` 필수 (빼면 ROS 노드가 두 번 뜸)
- 다른 PC에서 화면을 보려면: `sudo ufw allow 5000/tcp` 후 `http://관제PC_IP:5000`

main.py (`fms_manager` 폴더에서 실행 — `pcb_cv_inspector3_2`를 같은 폴더에서 불러옴):
```bash
cd ~/turtlebot_vision_amr/fms_manager && python3 main.py
```
- **모델 경로**: main.py가 자기 옆 `weights/best.pt`를 찾습니다 (`~/turtlebot_vision_amr/fms_manager/weights/best.pt`)
- **시리얼 포트**: main.py가 `/dev/ttyACM0` · 9600으로 되어 있습니다. 아두이노가 다른 이름이면 `ls /dev/ttyACM* /dev/ttyUSB*`로 확인해 팀원과 맞춥니다. 권한 오류면 `sudo usermod -aG dialout $USER` 후 다시 로그인
- 카메라 번호는 `0` 고정입니다. 웹캠이 다른 번호면 팀원과 맞춥니다

## 8. 확인

- [ ] 브라우저 `http://localhost:5000` → 지도 · 오늘 요약 · 이벤트 기록 창이 열리는지
- [ ] main.py 창에서 **Space**(검사) → DB에 저장되고, 관제 화면 스냅샷 · 최근 6건에 나오는지 (최대 2초 뒤)
- [ ] 사진이 "사진 없음"이면 `.env`의 `FMS_SNAPSHOT_DIR` 확인
- [ ] 통신 · 로봇 상태: main.py를 켜면 `/fms/status`(0.5초마다)로 "연결됨" · 상태 배지 · 지도 위치 · 속도 · 배터리가 나옵니다. main.py를 끄면 3초 뒤 "통신 끊김"
  ```bash
  ros2 topic echo /fms/status --once
  ```
- [ ] 영상 주소: web_video_server를 관제 PC에서 돌리면 `templates/index.html`의 `192.168.0.42:8080` → `localhost:8080`. 리눅스 PC(192.168.0.42)에서 계속 돌리면 그대로

### ROS 없이 화면만 시험하기 (`/fms/status` 흉내)

main.py 없이 화면만 볼 때 가짜 값을 넣을 수 있습니다 (main.py와 동시에 켜지 않기).
```bash
ros2 topic pub -r 2 /fms/status std_msgs/msg/String '{data: "{\"robot\": {\"mission_state\": \"WAIT_LOADING\", \"x\": 0.5, \"y\": 2.0, \"yaw_deg\": 90, \"speed\": 0.12, \"battery\": 0.8}, \"queue_length\": 1}"}'
```
배지 "적재 대기", 지도 (0.5, 2.0)에서 위쪽을 보는 로봇, 0.12 m/s, 80%가 나오면 정상. Ctrl+C로 멈추면 3초 뒤 "통신 끊김" 배너.

---

## 안 될 때

| 증상 | 원인 · 해결 |
|---|---|
| `* ROS: rclpy 없음` | `source /opt/ros/humble/setup.bash` 안 함 (2단계) |
| `MySQL 에 연결할 수 없습니다 … 1045 Access denied` | `.env` 비밀번호 오타. 그래도 안 되면 `FMS_DB_HOST=localhost`로 바꿔 보기 |
| `cryptography` 관련 오류 | `python3 -m pip install --user cryptography` (MySQL 8 비밀번호 방식) |
| `No module named 'flask'` | 다른 Python에 설치함 → `python3 -m pip install --user -r requirements.txt` |
| main.py가 켜자마자 DB 오류 | `~/turtlebot_vision_amr/fms_manager/.env` 없음 (5단계 복사) |
| main.py가 DB에 안 쓰고 화면에만 출력 | `~/turtlebot_vision_amr/fms_manager`에 `db_manager.py`가 없어서 main.py가 가짜 DB(Mock)로 돎 |
| `No module named 'pcb_cv_inspector3_2'` | `~/turtlebot_vision_amr/fms_manager`로 `cd` 안 하고 실행함 |
| main.py가 모델(best.pt)을 못 찾음 | `fms_manager/weights/best.pt`가 없음 (1단계) |
| 다른 PC에서 화면이 안 열림 | `--host 0.0.0.0` 빠짐 또는 방화벽 (7단계) |
| 계속 "수신 없음" | main.py가 안 켜짐, 또는 두 터미널 중 하나의 도메인 번호가 22가 아님 (`echo $ROS_DOMAIN_ID`) |
| 검사 사진 "사진 없음" | `.env`의 `FMS_SNAPSHOT_DIR`이 `~/turtlebot_vision_amr/fms_manager`이 아님 |
| 지도 위 로봇 위치가 어긋남 | 로봇 AMCL 지도와 관제 지도(`map_test1`)가 다른 파일 |

---

## 옮긴 뒤 이어서 할 작업

### 팀에게 받을 것
- [x] ~~main.py `/fms/status` 발행~~ (2026-10-29 팀원 커밋에 들어옴, 실물 확인 남음)
- [ ] (선택) 배터리 반올림 없이 · 처음 값 `None` · `robot.last_seen` · `update_delivery_complete`를 `try/except`로 · 통신 끊김을 DB에 남길지 (`TEAM_INTERFACE.md`)
- [ ] A\* 노드의 상태 이름 전체 (`mission_state`. main.py에서 확인한 6개는 `app.py` `MISSIONS`에 넣음: `IDLE_WAIT` · `MOVING_TO_INSPECT` · `WAIT_LOADING` · `MOVING_TO_DEST` · `WAIT_UNLOADING` · `RETURNING_HOME`) → 더 있으면 추가
- [ ] R 키(`RESET`)가 비상 정지인지 (화면 안내 문구 "main.py 창에서 R")
- [ ] **구역 좌표**: 대기 · 검사대 · 양품 · 불량의 실제 위치와 목표 좌표 → `config/zones.yaml` (지금은 임시 값)
- [ ] 로봇 AMCL이 `map_test1`과 **같은 지도 파일**을 쓰는지

### 관제 화면 쪽 남은 개발
- [ ] `/fms/status`가 오면: 계획 경로 · 현재 작업 번호 · 목적지 표시 (main.py가 보내 주면)
- [ ] 시안 코드 정리 (실제 값이 들어온 뒤): 지도 애니메이션(`placeRobot`, `progress`), `job` 고정값(작업 #40), 시안 미리보기 줄, `STATES`의 `timerFrom`
- [ ] `POST /api/robot` (개발용 가짜 입구) 삭제
- (결정 2026-10-29) DB 읽기는 (나) 방식: 화면이 `store.py`로 직접 읽음. db_manager에 읽기 함수는 넣지 않음

전체 목록은 `CLAUDE.md`의 "ROS 연동 때 정리 목록"에 있습니다.
