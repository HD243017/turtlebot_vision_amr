-- =============================================================================
-- 기판 검사 · 이송 관제 FMS — 테이블 생성 (MySQL 8.0)  · 설계 2안 (2026-10-22, 팀원 설계 계획 기준)
--
-- 실행: MySQL Workbench 에서 root 로 접속해 이 파일을 열고 실행(번개 아이콘).
--       여러 번 실행해도 안전하다 (이미 있으면 건너뜀). 데이터는 지우지 않는다.
--       ⚠ 1안(inspection_shot · inspection_defect 가 있던 구조)으로 이미 만들었다면
--         db/drop_v1.sql 을 먼저 실행해 옛 테이블을 지운 뒤 이 파일을 실행한다.
--
-- 테이블 3개
--   inspection : 검사 1회 = 1줄. 재촬영도 새 줄(새 검사 번호)로 쌓인다.
--   delivery   : 터틀봇 호출 · 주행 1회 = 1줄. 그 기판의 마지막 검사와 연결된다.
--   event      : 주행 중 장애물 정지 · 경로 재탐색 · 통신 끊김 · 비상 정지.
-- 이벤트 기록 창은 세 테이블을 시간순으로 합쳐 보여 준다 (화면 문구는 서버가 만든다).
-- 로봇이 지금 이송 중인지 같은 실시간 상태는 DB에 두지 않는다 (관제 서버 메모리).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS fms
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE fms;

-- -----------------------------------------------------------------------------
-- 검사 결과. 부품마다 검사 프로그램의 결과 코드를 그대로 문자열로 넣는다.
--   'PASS' / 'MISSING' / 'REVERSE' / 'OFFSET(14.2px)' / 'TILT(+4.5d)' / 'SHAPE(0.82)'
--   한 부품에 불량이 여러 개면 쉼표로 이어 쓴다: 'OFFSET(3.0px),TILT(+2.0d)'
-- 사진은 파일 경로만 저장한다 (예: 'logs/img_0001.jpg', 'pass/img_pass_0001.jpg').
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inspection (
  inspection_id   INT UNSIGNED         NOT NULL AUTO_INCREMENT COMMENT '검사 번호 (화면 #0042)',
  result          ENUM('PASS','FAIL')  NOT NULL                COMMENT '최종 판정',
  inspected_at    DATETIME             NOT NULL                COMMENT '검사 완료 시각',
  esp01_status    VARCHAR(40)          NOT NULL DEFAULT 'PASS',
  ic_chip_status  VARCHAR(40)          NOT NULL DEFAULT 'PASS',
  fnd_status      VARCHAR(40)          NOT NULL DEFAULT 'PASS',
  switch_status   VARCHAR(40)          NOT NULL DEFAULT 'PASS',
  img_path        VARCHAR(255)         NULL                    COMMENT '촬영 사진 경로 (사진 폴더 기준)',
  PRIMARY KEY (inspection_id),
  KEY idx_inspection_time (inspected_at)
) ENGINE=InnoDB COMMENT='검사 결과';

-- -----------------------------------------------------------------------------
-- 터틀봇 호출 및 주행 기록.
--   total_sec = 대기소 복귀 시작 - 호출 (오늘 평균 이송 시간 계산용)
--   재촬영으로 검사 번호가 바뀌면, 아직 출발 전인 주행은 새 검사로 연결을 옮긴다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delivery (
  delivery_id         INT UNSIGNED     NOT NULL AUTO_INCREMENT COMMENT '작업 번호 (화면 작업 #40)',
  inspection_id       INT UNSIGNED     NULL                    COMMENT '이 주행을 호출한 검사',
  dest_marker         TINYINT UNSIGNED NOT NULL                COMMENT '2 = 양품, 3 = 불량 (config/zones.yaml 마커)',
  called_at           DATETIME         NOT NULL                COMMENT '호출',
  station_arrived_at  DATETIME         NULL                    COMMENT '검사대 도착',
  departed_at         DATETIME         NULL                    COMMENT '하역장으로 출발',
  return_started_at   DATETIME         NULL                    COMMENT '대기소 복귀 시작',
  total_sec           INT UNSIGNED     NULL                    COMMENT '호출 ~ 대기소 복귀 시작 (초)',
  PRIMARY KEY (delivery_id),
  UNIQUE KEY uq_delivery_inspection (inspection_id),
  KEY idx_delivery_called (called_at),
  CONSTRAINT fk_delivery_inspection FOREIGN KEY (inspection_id)
    REFERENCES inspection (inspection_id) ON DELETE SET NULL
) ENGINE=InnoDB COMMENT='터틀봇 호출 및 주행 기록';

-- -----------------------------------------------------------------------------
-- 주행 중 이벤트.
--   OBSTACLE_STOP : 장애물(사람 포함) 감지로 일시 정지 → 3초 안에 풀려 그대로 재출발
--   REROUTE       : 3초 동안 장애물이 계속 있어 경로 재탐색 후 재출발
--   COMM_LOST     : 로봇 통신 끊김 (resumed_at = 복구 시각)
--   ESTOP         : 관제 화면 비상 정지 (resumed_at = 해제 시각)
-- 대기 중 비상 정지처럼 주행이 없을 때도 있어 delivery_id 는 비워 둘 수 있다.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event (
  event_id     INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  delivery_id  INT UNSIGNED  NULL     COMMENT '어떤 주행 중에 생겼는지',
  event_type   ENUM('OBSTACLE_STOP','REROUTE','COMM_LOST','ESTOP') NOT NULL,
  occurred_at  DATETIME      NOT NULL COMMENT '발생 (감지 · 일시 정지) 시각',
  x            DECIMAL(7,3)  NULL     COMMENT '발생 위치 (지도 좌표 m)',
  y            DECIMAL(7,3)  NULL,
  resumed_at   DATETIME      NULL     COMMENT '재출발 · 통신 복구 · 비상 정지 해제 시각',
  PRIMARY KEY (event_id),
  KEY idx_event_time (occurred_at),
  CONSTRAINT fk_event_delivery FOREIGN KEY (delivery_id)
    REFERENCES delivery (delivery_id) ON DELETE SET NULL
) ENGINE=InnoDB COMMENT='주행 중 이벤트';
