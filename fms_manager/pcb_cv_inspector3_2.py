import cv2
import numpy as np
import os
import time
from datetime import datetime
from ultralytics import YOLO

# pyserial 미설치 환경에서도 단독 테스트가 가능하도록 방어 처리
try:
    import serial
except ImportError:
    serial = None


class SerialHandler:
    # MCU(Nucleo/Arduino)와 시리얼 통신을 담당하는 클래스 (연결 실패 시에도 프로그램 유지)
    def __init__(self, port="/dev/ttyACM0", baudrate=115200, timeout=0.05):
        self.ser = None
        if serial is None:
            print("[INFO] pyserial 모듈 없음: 시리얼 비활성화 모드")
            return
        try:
            self.ser = serial.Serial(port, baudrate, timeout=timeout)
            print(f"[INFO] 시리얼 연결 성공: {port} ({baudrate}bps)")
        except Exception as e:
            print(f"[WARN] 시리얼 연결 실패 ({port}): 단독 테스트 모드로 동작 ({e})")

    def read_command(self):
        # MCU로부터 수신된 문자열 한 줄 반환 (없거나 에러 시 None)
        if self.ser is None or not self.ser.is_open:
            return None
        try:
            if self.ser.in_waiting > 0:
                return self.ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception as e:
            print(f"[ERROR] 시리얼 수신 오류: {e}")
        return None

    def send_command(self, cmd):
        # MCU로 명령 문자열 전송 (끝에 줄바꿈 자동 추가)
        if self.ser is None or not self.ser.is_open:
            print(f"[SERIAL-MOCK] 송신 생략 (미연결): {cmd}")
            return False
        try:
            msg = f"{cmd}\n".encode("utf-8")
            self.ser.write(msg)
            print(f"[SERIAL-TX] {cmd}")
            return True
        except Exception as e:
            print(f"[ERROR] 시리얼 송신 오류 ({cmd}): {e}")
            return False

    def close(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()


class PCBInspector:
    def __init__(self, model_path="best.pt", target_w=400, target_h=800, log_dir="logs"):
        self.target_w = target_w  # 원근 보정 후 출력 이미지 가로 크기 (px)
        self.target_h = target_h  # 원근 보정 후 출력 이미지 세로 크기 (px)
        self.log_dir = log_dir    # 결과 이미지 저장 최상위 폴더
        self.inspect_seq = 0      # 파일명 생성을 위한 검사 시퀀스 번호

        self.model = None
        if os.path.exists(model_path):
            try:
                self.model = YOLO(model_path)
                print(f"[INFO] YOLO 모델 로드 완료: {model_path}")
            except Exception as e:
                print(f"[WARN] YOLO 로드 오류 ({e}): 고정 ROI 모드")
        else:
            print(f"[WARN] '{model_path}' 파일 없음: 고정 ROI 모드")

        # YOLO 클래스 ID와 부품명 매핑
        self.class_map = {
            0: "fnd",
            1: "switch",
            2: "ic_chip",
            3: "esp01"
        }

        # 400x800 정규화 영상 기준 각 부품의 정위치 비율 (ymin_r, ymax_r, xmin_r, xmax_r)
        self.ref_roi_ratios = {
            "esp01":   (0.035, 0.230, 0.220, 0.680),
            "switch":  (0.295, 0.470, 0.240, 0.520),
            "ic_chip": (0.300, 0.555, 0.580, 0.820),
            "fnd":     (0.520, 0.970, 0.130, 0.550),
        }

        self.angle_targets = ["ic_chip", "fnd"]  # 회전 각도 검사를 수행할 부품 목록
        self.ANGLE_TOLERANCE = 3.0               # 회전 각도 허용 임계값 (도)
        self.OFFSET_TOLERANCE_PX = 12.0          # 중심점 위치 이탈 허용 임계값 (px)
        self.BBOX_PAD = 8                        # YOLO 검출 박스에 추가할 여백 (px)

    def order_points(self, pts):
        # 4개의 코너 좌표를 [좌상, 우상, 우하, 좌하] 순서로 정렬
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]     # x+y 최소: 좌상
        rect[2] = pts[np.argmax(s)]     # x+y 최대: 우하
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]  # y-x 최소: 우상
        rect[3] = pts[np.argmax(diff)]  # y-x 최대: 좌하
        return rect

    def find_board_corners_auto(self, frame):
        # 영상에서 밝은 보드 외곽선 4개 코너 좌표를 찾아 반환 (실패 시 None 반환)
        if frame is None:
            return None

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        # Otsu 알고리즘으로 보드 배경과 어두운 바닥 분리
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 모폴로지 닫힘 연산으로 보드 내부 구멍 및 부품 사이 빈틈 메우기
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        main_c = max(contours, key=cv2.contourArea)
        # 가장 큰 외곽선 면적이 전체 화면의 10% 미만이면 보드가 없는 것으로 판정
        if cv2.contourArea(main_c) < (w * h * 0.10):
            return None

        peri = cv2.arcLength(main_c, True)
        approx = cv2.approxPolyDP(main_c, 0.03 * peri, True)

        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype("float32")
        else:
            rect = cv2.minAreaRect(main_c)
            pts = cv2.boxPoints(rect).astype("float32")

        return self.order_points(pts)

    def warp_and_normalize(self, frame):
        # 보드 코너 검출 후 400x800 원근 보정 및 CLAHE 조도 평활화 수행 (실패 시 None 반환)
        pts = self.find_board_corners_auto(frame)
        if pts is None:
            print("보드 자동 검출 실패")
            return None

        dst = np.array([
            [0, 0],
            [self.target_w - 1, 0],
            [self.target_w - 1, self.target_h - 1],
            [0, self.target_h - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(pts, dst)
        warped = cv2.warpPerspective(frame, M, (self.target_w, self.target_h))

        # LAB 색공간 L(명도) 채널에 CLAHE를 적용하여 조명 편차 보정
        lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        normalized = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

        return normalized

    def get_reference_rois(self, h, w):
        # 비율 좌표를 실제 픽셀 좌표 (ymin, ymax, xmin, xmax)로 변환
        rois = {}
        for name, (ymin_r, ymax_r, xmin_r, xmax_r) in self.ref_roi_ratios.items():
            rois[name] = (int(h * ymin_r), int(h * ymax_r), int(w * xmin_r), int(w * xmax_r))
        return rois

    def detect_and_extract_rois(self, image, conf_thres=0.35):
        # YOLO로 부품을 검출하여 잘라낸 이미지(cropped_dict)와 좌표(detected_rois) 반환
        # ymin: 박스 상단 y, ymax: 박스 하단 y, xmin: 박스 좌측 x, xmax: 박스 우측 x
        h, w = image.shape[:2]
        cropped_dict, detected_rois, yolo_meta = {}, {}, {}

        if self.model is not None:
            results = self.model.predict(image, conf=conf_thres, verbose=False)[0]
            for box in results.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                if cls_id not in self.class_map:
                    continue
                comp_name = self.class_map[cls_id]
                # 동일 부품이 중복 검출된 경우 신뢰도(conf)가 가장 높은 박스만 유지
                if comp_name in yolo_meta and yolo_meta[comp_name]["conf"] >= conf:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                ymin = max(0, y1 - self.BBOX_PAD)
                ymax = min(h, y2 + self.BBOX_PAD)
                xmin = max(0, x1 - self.BBOX_PAD)
                xmax = min(w, x2 + self.BBOX_PAD)

                detected_rois[comp_name] = (ymin, ymax, xmin, xmax)
                cropped_dict[comp_name] = image[ymin:ymax, xmin:xmax].copy()
                yolo_meta[comp_name] = {"conf": conf, "raw_box": (y1, y2, x1, x2)}
        else:
            detected_rois = self.get_reference_rois(h, w)
            for name, (ymin, ymax, xmin, xmax) in detected_rois.items():
                cropped_dict[name] = image[ymin:ymax, xmin:xmax].copy()
                yolo_meta[name] = {"conf": 1.0, "raw_box": (ymin, ymax, xmin, xmax)}

        return cropped_dict, detected_rois, yolo_meta

    def measure_component_tilt(self, roi_bgr):
        # 부품 ROI 내부의 모멘트를 계산하여 기울어진 각도(tilt_angle)와 외곽 박스 반환
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 85, 255, cv2.THRESH_BINARY_INV)
        # ROI 가장자리 노이즈 제거
        thresh[:4, :] = 0; thresh[-4:, :] = 0; thresh[:, :4] = 0; thresh[:, -4:] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return 0.0, None, "NO_CONTOUR"

        main_c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(main_c) < 500:
            return 0.0, None, "AREA_TOO_SMALL"

        hull = cv2.convexHull(main_c)
        solid_blob = np.zeros_like(gray)
        cv2.drawContours(solid_blob, [hull], -1, 255, thickness=cv2.FILLED)

        M = cv2.moments(solid_blob, binaryImage=True)
        tilt_angle = -0.5 * np.degrees(np.arctan2(2.0 * M["mu11"], M["mu02"] - M["mu20"]))
        rect = cv2.minAreaRect(hull)
        box = np.intp(cv2.boxPoints(rect))

        is_pass = abs(tilt_angle) <= self.ANGLE_TOLERANCE
        return tilt_angle, box, ("PASS" if is_pass else "FAIL_TILT")

    def check_esp01_orientation(self, esp_roi):
        # ESP-01 안테나(금색 패턴 및 엣지)가 우측에 편중되어 있는지 비율로 역삽 여부 판정
        h, w = esp_roi.shape[:2]
        hsv = cv2.cvtColor(esp_roi, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, np.array([10, 40, 90]), np.array([35, 255, 255]))
        gray = cv2.cvtColor(esp_roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 150)
        combined_mask = cv2.bitwise_or(color_mask, edges)

        mid_x = w // 2
        left_cnt = cv2.countNonZero(combined_mask[:, :mid_x])
        right_cnt = cv2.countNonZero(combined_mask[:, mid_x:])
        right_ratio = right_cnt / (left_cnt + right_cnt + 1e-5)

        is_normal = right_ratio >= 0.55
        return ("PASS" if is_normal else "FAIL_REVERSE"), right_ratio

    def measure_component_centroid_in_roi(self, roi_bgr):
        # 부품 ROI 내부의 1차 모멘트로 부품 무게중심 좌표 (cx, cy) 반환
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 85, 255, cv2.THRESH_BINARY_INV)
        thresh[:4, :] = 0; thresh[-4:, :] = 0; thresh[:, :4] = 0; thresh[:, -4:] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        main_c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(main_c) < 400:
            return None

        hull = cv2.convexHull(main_c)
        solid_blob = np.zeros_like(gray)
        cv2.drawContours(solid_blob, [hull], -1, 255, thickness=cv2.FILLED)

        M = cv2.moments(solid_blob, binaryImage=True)
        if M["m00"] == 0:
            return None
        return (M["m10"] / M["m00"], M["m01"] / M["m00"])

    def save_inspection_image(self, result_img, final_decision):
        # 판정 결과에 따라 logs/pass 또는 logs/fail 폴더에 이미지 저장 후 경로 문자열 반환
        sub_dir = "pass" if final_decision == "PASS" else "fail"
        save_dir = os.path.join(self.log_dir, sub_dir)
        os.makedirs(save_dir, exist_ok=True)

        self.inspect_seq += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{sub_dir}_{timestamp}_{self.inspect_seq:04d}.jpg"
        # DB 저장을 위해 슬래시(/) 경로로 통일
        rel_path = f"{self.log_dir}/{sub_dir}/{filename}"

        try:
            cv2.imwrite(rel_path, result_img)
            cv2.imwrite("latest_inspection_result.jpg", result_img)
        except Exception as e:
            print(f"[ERROR] 이미지 저장 실패: {e}")

        return rel_path

    def run_unified_inspection(self, warped_img):
        # 정규화된 보드 이미지를 입력받아 불량 판정 후 (결과이미지, DB저장용 딕셔너리) 반환
        if warped_img is None:
            return None, None

        clean_img = warped_img.copy()
        result_img = warped_img.copy()
        h, w = clean_img.shape[:2]

        ref_rois = self.get_reference_rois(h, w)
        cropped_dict, detected_rois, _ = self.detect_and_extract_rois(clean_img)
        defect_summary = {name: [] for name in self.ref_roi_ratios.keys()}

        print("\n" + "=" * 55)
        print(f" [검사 시작] 검출된 부품 수: {len(cropped_dict)} / {len(self.ref_roi_ratios)}")
        print("=" * 55)

        # ry1: 기준 상단 y, ry2: 기준 하단 y, rx1: 기준 좌측 x, rx2: 기준 우측 x
        for name, (ry1, ry2, rx1, rx2) in ref_rois.items():
            if name not in cropped_dict:
                defect_summary[name].append("MISSING")
                cv2.rectangle(result_img, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2)
                cv2.putText(result_img, f"{name}: MISSING", (rx1, max(15, ry1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2, cv2.LINE_AA)
                print(f" [FAIL] [{name.upper():<8}] 불량: 부품 누락 (MISSING)")
                continue

            roi_crop = cropped_dict[name]
            ymin, ymax, xmin, xmax = detected_rois[name]
            logs = []

            # 1. 중심점 위치 이탈 검사 (ref_cx, ref_cy: 기준 중심 / act_cx, act_cy: 실제 중심)
            ref_cx, ref_cy = (rx1 + rx2) / 2.0, (ry1 + ry2) / 2.0
            local_c = self.measure_component_centroid_in_roi(roi_crop)
            if local_c is not None:
                act_cx, act_cy = xmin + local_c[0], ymin + local_c[1]
            else:
                act_cx, act_cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0

            dist = np.sqrt((act_cx - ref_cx) ** 2 + (act_cy - ref_cy) ** 2)
            if dist > self.OFFSET_TOLERANCE_PX:
                defect_summary[name].append(f"OFFSET({dist:.1f}px)")
                logs.append(f"위치이탈 {dist:.1f}px")
                cv2.circle(result_img, (int(ref_cx), int(ref_cy)), 3, (255, 200, 0), -1)
                cv2.circle(result_img, (int(act_cx), int(act_cy)), 3, (0, 0, 255), -1)
                cv2.line(result_img, (int(ref_cx), int(ref_cy)), (int(act_cx), int(act_cy)), (0, 0, 255), 1)
            else:
                logs.append(f"위치정상({dist:.1f}px)")

            # 2. 회전 각도 검사 (ic_chip, fnd 대상)
            tilt_box = None
            if name in self.angle_targets:
                tilt_angle, box, tilt_status = self.measure_component_tilt(roi_crop)
                if tilt_status != "PASS":
                    defect_summary[name].append(f"TILT({tilt_angle:+.1f}d)")
                    logs.append(f"각도불량 {tilt_angle:+.1f}도")
                    if box is not None:
                        tilt_box = box + np.array([xmin, ymin])
                else:
                    logs.append(f"각도정상({tilt_angle:+.1f}도)")

            # 3. 역삽 검사 (esp01 대상)
            if name == "esp01":
                esp_status, ratio = self.check_esp01_orientation(roi_crop)
                if esp_status != "PASS":
                    defect_summary[name].append("REVERSE")
                    logs.append(f"역삽불량(우측비율 {ratio:.2f})")
                else:
                    logs.append(f"방향정상({ratio:.2f})")

            # 개별 부품 결과 렌더링
            comp_defects = defect_summary[name]
            if len(comp_defects) == 0:
                cv2.rectangle(result_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 1)
                cv2.putText(result_img, f"{name}: PASS", (xmin, max(15, ymin - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 200, 0), 1, cv2.LINE_AA)
                print(f" [PASS] [{name.upper():<8}] 정상 | {', '.join(logs)}")
            else:
                if tilt_box is not None:
                    cv2.drawContours(result_img, [tilt_box], 0, (0, 0, 255), 2)
                else:
                    cv2.rectangle(result_img, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)

                err_str = ",".join(comp_defects)
                cv2.putText(result_img, f"{name}: {err_str}", (xmin, max(15, ymin - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1, cv2.LINE_AA)
                print(f" [FAIL] [{name.upper():<8}] 불량 [{err_str}] | 상세: {', '.join(logs)}")

        total_defects = sum(len(v) for v in defect_summary.values())
        final_decision = "PASS" if total_defects == 0 else "FAIL"
        banner_color = (0, 200, 0) if final_decision == "PASS" else (0, 0, 255)

        cv2.rectangle(result_img, (0, 0), (w, 32), (30, 30, 30), -1)
        cv2.putText(result_img, f"FINAL RESULT: {final_decision} (Defects: {total_defects})",
                    (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, banner_color, 2, cv2.LINE_AA)

        img_path = self.save_inspection_image(result_img, final_decision)
        inspected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # DB 테이블 컬럼 규격에 맞춘 결과 딕셔너리 생성 (불량이 없으면 'PASS', 있으면 콤마로 연결)
        db_record = {
            "final_decision": final_decision,
            "inspected_at": inspected_at,
            "esp01_status": ",".join(defect_summary["esp01"]) if defect_summary["esp01"] else "PASS",
            "ic_chip_status": ",".join(defect_summary["ic_chip"]) if defect_summary["ic_chip"] else "PASS",
            "fnd_status": ",".join(defect_summary["fnd"]) if defect_summary["fnd"] else "PASS",
            "switch_status": ",".join(defect_summary["switch"]) if defect_summary["switch"] else "PASS",
            "img_path": img_path
        }

        print("-" * 55)
        print(f" >>> [최종 보드 판정]: {final_decision} (총 불량 항목: {total_defects}건)")
        print(f" >>> [DB 레코드 생성]: {db_record}")
        print("=" * 55 + "\n")

        return result_img, db_record


def execute_inspection_sequence(cap, inspector, serial_handler=None, db_manager=None, robot_caller=None, triggered_by_mcu=False):
    # 조명 점등 -> 노출 대기 -> 촬영 -> 분석 -> DB 저장 -> 로봇 호출 -> MCU 결과 전송 통합 시퀀스
    # triggered_by_mcu가 False(PC 스페이스바/UI 클릭)일 때만 MCU에 촬영 조명 점등 신호 전송
    if not triggered_by_mcu and serial_handler is not None:
        serial_handler.send_command("LED_ON")

    # 조명 점등 후 웹캠 노출 안정화 대기 (0.3초 동안 카메라 버퍼를 비워 최신 밝은 프레임 확보)
    t_end = time.time() + 0.3
    latest_frame = None
    while time.time() < t_end:
        ret, f = cap.read()
        if ret:
            latest_frame = cv2.flip(f, -1)
        cv2.waitKey(10)

    if latest_frame is None:
        print("[ERROR] 카메라 프레임을 읽을 수 없습니다.")
        if serial_handler is not None:
            serial_handler.send_command("ERR_NO_BOARD")
        return None, None

    # 1. 보드 검출 및 원근 보정 (검출 실패 시 None 반환 -> 리사이즈 없이 중단)
    warped_board = inspector.warp_and_normalize(latest_frame)
    if warped_board is None:
        # MCU에 검출 실패 신호 전송 (조명 끄고 재투입 유도)
        if serial_handler is not None:
            serial_handler.send_command("ERR_NO_BOARD")
        return None, None

    # 2. 부품 불량 분석 수행
    result_img, db_record = inspector.run_unified_inspection(warped_board)

    # 3. MCU로 판정 결과 전송 (MCU는 조명을 끄고 결과에 맞춰 초록/빨간불 또는 LCD 출력)
    if serial_handler is not None:
        serial_handler.send_command(f"RES_{db_record['final_decision']}")

    # 4. 외부 DB 매니저 연동 (객체가 주입된 경우에만 실행, 에러 발생 시에도 죽지 않음)
    if db_manager is not None:
        try:
            db_manager.insert_inspection_result(db_record)
            print("[INFO] DB 저장 완료")
        except Exception as e:
            print(f"[ERROR] DB 저장 실패 (무시하고 계속 진행): {e}")
    else:
        print("[DB-MOCK] 연결된 DB 매니저 없음 (콘솔 출력으로 대체)")

    # 5. 터틀봇 호출 모듈 연동 (콜백 함수나 객체가 주입된 경우에만 실행)
    if robot_caller is not None:
        try:
            robot_caller(db_record)
            print("[INFO] 터틀봇 호출 요청 완료")
        except Exception as e:
            print(f"[ERROR] 터틀봇 호출 실패 (무시하고 계속 진행): {e}")
    else:
        print("[ROBOT-MOCK] 연결된 로봇 호출기 없음")

    return result_img, db_record


def main():
    inspector = PCBInspector(model_path="best.pt")
    # 포트 번호는 실제 뉴클레오/아두이노 연결 환경에 맞춰 변경 (미연결 시 자동으로 MOCK 동작)
    serial_handler = SerialHandler(port="COM3", baudrate=115200)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 웹캠을 열 수 없습니다.")
        return

    print("\n" + "=" * 50)
    print(" [검사 시스템 대기 중]")
    print("  - MCU 시리얼 수신: 'REQ_CAPTURE' 수신 시 자동 검사")
    print("  - PC 수동 트리거 : [Space 바] 입력 시 조명 점등 후 검사")
    print("  - 종료           : [Q 키]")
    print("=" * 50 + "\n")

    board_ready_from_mcu = False

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, -1)
        display_frame = frame.copy()

        # 1. MCU 시리얼 신호 비차단(Non-blocking) 확인
        mcu_cmd = serial_handler.read_command()
        if mcu_cmd == "BOARD_IN":
            # MCU가 보드 투입 감지 후 기본 불 1개를 켰음을 알림
            board_ready_from_mcu = True
            print("[MCU] 보드 투입 감지됨 (대기 조명 점등 상태)")
        elif mcu_cmd == "REQ_CAPTURE":
            # MCU 물리 버튼이 눌려 촬영 조명이 켜졌으므로 즉시 검사 시퀀스 진입
            print("[MCU] 촬영 버튼 입력 수신: 검사를 시작합니다.")
            res_img, _ = execute_inspection_sequence(
                cap, inspector, serial_handler=serial_handler, triggered_by_mcu=True
            )
            if res_img is not None:
                cv2.imshow("Inspection Result", res_img)
            board_ready_from_mcu = False

        # 2. 화면 가이드라인 표시
        auto_corners = inspector.find_board_corners_auto(frame)
        if auto_corners is not None:
            cv2.polylines(display_frame, [auto_corners.astype(np.int32)], True, (0, 255, 0), 2)
            detect_txt = "PCB: LOCKED (Ready)"
            txt_color = (0, 255, 0)
        else:
            detect_txt = "PCB: NOT DETECTED"
            txt_color = (0, 0, 255)

        cv2.rectangle(display_frame, (0, 0), (display_frame.shape[1], 45), (30, 30, 30), -1)
        cv2.putText(display_frame, f"SPACE or MCU BTN | {detect_txt}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, txt_color, 2, cv2.LINE_AA)

        cv2.imshow("Live Camera", display_frame)

        # 3. PC 키보드 수동 제어
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            break
        elif key == ord(" "):
            print("[PC] 수동 촬영 입력 감지: MCU 조명 점등 요청 및 검사 시작")
            res_img, _ = execute_inspection_sequence(
                cap, inspector, serial_handler=serial_handler, triggered_by_mcu=False
            )
            if res_img is not None:
                cv2.imshow("Inspection Result", res_img)

    serial_handler.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()