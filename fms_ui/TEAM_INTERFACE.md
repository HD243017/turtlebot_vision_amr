# main.py ↔ 관제 화면 · DB매니저 연결 약속

> 작성 2026-10-26 (UI · DB 담당), **2026-10-29 팀원 `main.py` 기준으로 다시 씀**.
> - **팀원 담당**: 터틀봇, A\*, 검사대, `main.py`
> - **UI · DB 담당**: 관제 화면(웹 화면 + 화면 서버), `db_manager.py`, DB
>
> main.py는 **2026-10-29 팀원 커밋** 기준 (L · U 키 상태 확인, `LOAD_PASS`/`LOAD_FAIL`, 시리얼 `/dev/ttyACM0` · 9600, 모델 `main.py 옆 weights/best.pt`, `/fms/status` 발행 포함 — 같은 날 두 번째 커밋).
> 폴더 구성: `turtlebot_vision_amr/fms_manager/`(main.py · 검사 · `weights/best.pt` · `db_manager.py` · `.env` · `logs/`) + `turtlebot_vision_amr/fms_ui/`(관제 화면 서버).
> 10-26 첫 제안(상태 이름 9개, `/fms/command`, 재촬영 버튼 등)은 쓰지 않습니다. 이전 내용은 `.backup/before-docs_20261029_0928/TEAM_INTERFACE.md`.

## 0. 전체 흐름

```
터틀봇 · A* ◀─/task_command · /robot_state 등─▶ main.py
검사대(웹캠 · 시리얼) ◀──────────────────────▶ main.py
main.py ──(1) /fms/status 토픽──▶ 관제 화면 (보기 전용)
main.py ──(2) db_manager 함수 호출──▶ db_manager.py ──▶ MySQL
관제 화면 ──읽기만(store.py, DB매니저 안 거침)──▶ MySQL   (최근 검사 · 오늘 요약 · 이벤트 기록)
터틀봇 카메라 ──web_video_server──▶ 관제 화면 (main.py 안 거침)
```

- **관제 화면은 로봇으로 아무것도 보내지 않습니다.** 비상 정지 · 적재 완료 · 하역 완료는 main.py 창의 키(R · L · U)로 합니다. (`/fms/command`, `/cmd_vel/lock` 발행 없음)
- **DB에 쓰는 곳은 main.py 하나**(db_manager 함수를 통해서). 관제 화면은 읽기만 합니다.
- **DB 읽기는 (나) 방식으로 결정 (2026-10-29)**: 관제 화면 서버가 자기 코드(`store.py`)로 MySQL을 직접 읽습니다(최근 검사 · 오늘 요약 · 이벤트 기록). main.py가 DB 정보를 `/fms/status`에 담아 보낼 필요가 없고, db_manager에 읽기 함수도 추가하지 않습니다. 통신 끊김도 관제 화면이 DB에 기록하지 않습니다(남기려면 main.py가 `open_event("COMM_LOST")` / `close_event("COMM_LOST")`, 선택). 비교 근거: Claude 문서 "관제 화면 DB 정보 전달 방식 비교 (가)·(나)".
- 모두 관제 PC 한 대, `ROS_DOMAIN_ID=22`, DB는 관제 PC 로컬 MySQL.

---

## 1. main.py → 관제 화면 : `/fms/status` (요청)

**2026-10-29 두 번째 커밋에 들어왔습니다 (완료).** main.py가 만들고 있는 `system_state`를 그대로 보냅니다. 아래는 기록용.

- 타입 `std_msgs/String` (JSON), **0.5초마다** 계속 발행 (값이 안 바뀌어도). QoS 기본.
- 관제 화면은 이 토픽이 3초 넘게 안 오면 "통신 끊김"으로 표시합니다.

```python
# __init__ 에
self.pub_fms_status = self.create_publisher(String, '/fms/status', 10)
self.create_timer(0.5, self.publish_fms_status)

def publish_fms_status(self):
    msg = String()
    msg.data = json.dumps(self.system_state, ensure_ascii=False)
    self.pub_fms_status.publish(msg)
```

관제 화면이 쓰는 키 (`system_state` 그대로):

| 키 | 화면 | 비고 |
|---|---|---|
| `robot.mission_state` | 상태 배지 (한글) | `IDLE_WAIT` 대기 · `MOVING_TO_INSPECT` 검사대로 이동 · `WAIT_LOADING` 적재 대기 · `MOVING_TO_DEST` 이송 중 · `WAIT_UNLOADING` 하역 대기 · `RETURNING_HOME` 복귀 중. 그 밖은 "주행 중" |
| `robot.x` · `robot.y` · `robot.yaw_deg` | 지도의 로봇 위치 · 방향 | map 좌표 m, 각도는 도(°) |
| `robot.speed` | 속도 m/s | 음수면 절댓값 |
| `robot.battery` | 배터리 % | 0~1 또는 0~100 둘 다 받음 |
| `robot.front_dist` | (지금 화면에 칸 없음, 서버에 저장만) | |
| `queue_length` | (서버에 저장만) | |

**부탁 (가능하면)**
- `cb_battery`의 `round(msg.percentage, 1)` → 반올림 없이 `msg.percentage` (지금은 0.76이 0.8 → 80%로 보임)
- 배터리 처음 값 `100.0` → `None` (실제 값을 받기 전에 100%로 보이지 않게)
- `robot.last_seen`: 터틀봇에서 마지막으로 무언가 받은 시각(`time.time()`). 없으면 관제 화면은 "main.py가 살아 있는지"로만 통신을 판단합니다(로봇이 꺼져도 main.py가 보내면 "연결됨").

---

## 2. main.py → db_manager : 함수 호출 (완료)

`db_manager.py`는 main.py가 쓰는 이름에 맞춰 두었습니다. **main.py는 고칠 것이 없습니다.**

```python
from db_manager import DBManager
db_mgr = DBManager()        # 접속 정보는 db_manager.py 옆의 .env 에서 읽음
```

| 언제 (지금 main.py) | 부르는 함수 | 하는 일 |
|---|---|---|
| 검사 끝 (`execute_inspection_sequence` 안) | `insert_inspection_result(db_record)` | `inspection` 1줄 저장, 새 번호를 `db_record["job_id"]`에 넣어 둠 |
| 하역 후 복귀 시작 (`WAIT_UNLOADING` → `RETURNING_HOME`) | `update_delivery_complete(job_id, elapsed_sec)` | `delivery` 1줄 (호출 시각 = 지금 − elapsed, 목적지 PASS→2 / FAIL→3, 복귀 시작 · total_sec) |

- `db_record` 키: `final_decision`(PASS/FAIL) · `inspected_at`(`YYYY-MM-DD HH:MM:SS`) · `esp01_status` · `ic_chip_status` · `fnd_status` · `switch_status` · `img_path`
- 잘못된 값이면 `ValueError`. **`update_delivery_complete`는 ROS 콜백 안에서 불리므로 `try/except`로 감싸 주세요** (DB 오류로 노드가 멈추지 않게).
- `fms_manager/`에 `db_manager.py`가 없으면 main.py가 가짜 DB(Mock)로 돌아 DB에 아무것도 안 남습니다.

### 더 기록하고 싶을 때 (선택)
지금 main.py는 검사 · 복귀 시작만 기록합니다. 아래를 부르면 이벤트 기록 창이 더 자세해집니다.

| 언제 | 함수 |
|---|---|
| 터틀봇 호출 (`dispatch_next_job`) | `start_delivery(inspection_id, dest_marker)` → 이송 번호 (그러면 `update_delivery_complete`가 같은 줄을 이어 씀) |
| 검사대 도착 · 하역장 출발 | `mark_delivery(delivery_id, "station_arrived" / "departed")` |
| 장애물 정지 · 재탐색 · 통신 끊김 · 비상 정지 | `open_event(event_type, delivery_id, x, y)` → 풀리면 `close_event(event_type)` (통신 끊김은 관제 화면이 기록하지 않으므로 남기려면 여기서) |

---

## 3. DB 테이블 (`db/schema.sql`, MySQL 8, DB 이름 `fms`)

- `inspection`: inspection_id · result(PASS/FAIL) · inspected_at · 부품 4개 상태 · img_path(`logs/...`, main.py 폴더 기준)
- `delivery`: delivery_id · inspection_id · dest_marker(2 양품 / 3 불량) · called_at · station_arrived_at · departed_at · return_started_at · total_sec
- `event`: event_id · delivery_id · event_type(`OBSTACLE_STOP` / `REROUTE` / `COMM_LOST` / `ESTOP`) · occurred_at · x · y · resumed_at

---

## 4. 팀원에게 확인할 것

1. ~~`/fms/status` 발행 추가~~ (완료, 10-29 두 번째 커밋)
2. A\* 노드의 `mission_state`가 위 6개 말고 더 있는지 (화면 한글 배지용, 코드로 줘도 됨)
3. R 키(`RESET`)가 비상 정지인지, 리셋인지 (관제 화면 안내 문구 "비상 정지 · main.py 창에서 R")
4. ~~모델 경로~~ → 두 번째 커밋에서 main.py 옆 `weights/best.pt`로 해결. 대신 모서리 그리기의 `np`가 카메라 없는 분기에서만 import되어, 카메라가 켜져 있고 모서리를 찾으면 오류 → 맨 위에 `import numpy as np` 부탁. `fms_manager/.gitignore`에 `.env` · `logs/` · `latest_inspection_result.jpg`도 부탁
5. 실제 구역 좌표(대기 · 검사대 · 양품 · 불량)와 로봇 AMCL 지도가 `map_test1`인지
6. (알림) DB 읽기는 (나) 방식: 관제 화면이 직접 읽으므로 main.py 추가 작업 없음. 통신 끊김을 DB에 남길지만 정해 주세요.
