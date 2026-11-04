-- =============================================================================
-- 시안용 예시 데이터 (MySQL 8.0). schema.sql 을 먼저 실행한 뒤 실행한다.
--
-- ⚠ 이 파일은 기존 데이터를 모두 지우고 예시로 다시 채운다. 개발 PC에서만 쓴다.
-- 시각은 '실행 직전 15분'으로 잡혀서 언제 실행해도 화면의 오늘 요약에 나온다.
-- 사진은 snapshots/ 의 샘플(sample_board.jpg)을 가리킨다.
-- store.py 의 메모리 저장소(MemoryStore)도 같은 내용이다. 한쪽을 바꾸면 같이 바꾼다.
--
-- 들어가는 내용
--   검사 7건 (#0037~#0043): #0042 는 기판이 비뚤게 놓여 재촬영 → #0043 이 그 기판의 최종 검사
--   주행 6건 (작업 #35~#40): 5건 복귀 시작까지 끝남, #40 은 하역장으로 가는 중
--   이벤트 3건: 경로 재탐색 · 통신 끊김 · 장애물 일시 정지
-- =============================================================================

USE fms;

-- 예시 시각은 '실행 직전 15분' 안에 배치한다 (새 기록이 항상 예시보다 뒤에 쌓이도록).
-- 자정 직후에 실행하면 오늘 0시부터 시작한다.
SET @t0 = GREATEST(CAST(CURDATE() AS DATETIME), NOW() - INTERVAL 15 MINUTE);

-- 지우는 순서: 자식 → 부모
DELETE FROM event;
DELETE FROM delivery;
DELETE FROM inspection;

-- ---- 검사 ------------------------------------------------------------------
INSERT INTO inspection (inspection_id, result, inspected_at, esp01_status, ic_chip_status, fnd_status, switch_status, img_path) VALUES
  (37, 'PASS', ADDTIME(@t0,'0:00:00'), 'PASS',    'PASS',        'PASS',           'PASS',           'sample_board.jpg'),
  (38, 'PASS', ADDTIME(@t0,'0:02:15'), 'PASS',    'PASS',        'PASS',           'PASS',           'sample_board.jpg'),
  (39, 'PASS', ADDTIME(@t0,'0:04:57'), 'PASS',    'PASS',        'PASS',           'PASS',           'sample_board.jpg'),
  (40, 'FAIL', ADDTIME(@t0,'0:07:25'), 'PASS',    'TILT(+4.1d)', 'PASS',           'PASS',           'sample_board.jpg'),
  (41, 'PASS', ADDTIME(@t0,'0:09:45'), 'PASS',    'PASS',        'PASS',           'PASS',           'sample_board.jpg'),
  -- #0042: 기판이 비뚤게 놓여 위치 이탈 → 관제 화면에서 재촬영 → #0043 에서 ESP-01 누락 확정
  (42, 'FAIL', ADDTIME(@t0,'0:11:35'), 'PASS',    'PASS',        'OFFSET(19.3px)', 'OFFSET(16.8px)', 'sample_board.jpg'),
  (43, 'FAIL', ADDTIME(@t0,'0:11:53'), 'MISSING', 'PASS',        'PASS',           'PASS',           'sample_board.jpg');

-- ---- 주행 ------------------------------------------------------------------
INSERT INTO delivery (delivery_id, inspection_id, dest_marker, called_at, station_arrived_at, departed_at, return_started_at, total_sec) VALUES
  (35, 37, 2, ADDTIME(@t0,'0:00:03'), ADDTIME(@t0,'0:00:25'), ADDTIME(@t0,'0:00:41'), ADDTIME(@t0,'0:01:47'), 104),
  (36, 38, 2, ADDTIME(@t0,'0:02:18'), ADDTIME(@t0,'0:02:39'), ADDTIME(@t0,'0:02:54'), ADDTIME(@t0,'0:04:11'), 113),
  (37, 39, 2, ADDTIME(@t0,'0:05:00'), ADDTIME(@t0,'0:05:21'), ADDTIME(@t0,'0:05:36'), ADDTIME(@t0,'0:06:36'),  96),
  (38, 40, 3, ADDTIME(@t0,'0:07:28'), ADDTIME(@t0,'0:07:50'), ADDTIME(@t0,'0:08:06'), ADDTIME(@t0,'0:09:26'), 118),
  (39, 41, 2, ADDTIME(@t0,'0:09:48'), ADDTIME(@t0,'0:10:10'), ADDTIME(@t0,'0:10:26'), ADDTIME(@t0,'0:11:26'),  98),
  (40, 43, 3, ADDTIME(@t0,'0:11:55'), ADDTIME(@t0,'0:12:09'), ADDTIME(@t0,'0:12:36'), NULL,                    NULL);

-- ---- 이벤트 ----------------------------------------------------------------
INSERT INTO event (delivery_id, event_type, occurred_at, x, y, resumed_at) VALUES
  (36, 'REROUTE',       ADDTIME(@t0,'0:03:25'), 1.300, 0.720, ADDTIME(@t0,'0:03:29')),
  (38, 'COMM_LOST',     ADDTIME(@t0,'0:08:45'), NULL,  NULL,  ADDTIME(@t0,'0:08:47')),
  (40, 'OBSTACLE_STOP', ADDTIME(@t0,'0:13:07'), 1.050, 0.720, ADDTIME(@t0,'0:13:09'));
