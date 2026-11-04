-- =============================================================================
-- 1안 테이블 지우기 (한 번만). 1안 구조로 fms DB를 이미 만든 PC에서,
-- 2안 schema.sql 을 실행하기 전에 root 로 실행한다.
--
-- ⚠ 들어 있는 데이터가 모두 지워진다. 개발 PC 전용 (지금은 예시 데이터뿐).
-- 순서: 이 파일 → schema.sql → seed.sql
-- =============================================================================

USE fms;

DROP TABLE IF EXISTS event;
DROP TABLE IF EXISTS delivery;
DROP TABLE IF EXISTS inspection_defect;
DROP TABLE IF EXISTS inspection_shot;
DROP TABLE IF EXISTS inspection;
