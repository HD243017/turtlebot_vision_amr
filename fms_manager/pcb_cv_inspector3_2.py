import cv2
import numpy as np
import os
import time
from datetime import datetime
from ultralytics import YOLO

try:
    import serial
except ImportError:
    serial = None


class SerialHandler:
    def __init__(self, port="/dev/ttyACM0", baudrate=9600, timeout=0.05):
        self.ser = None
        if serial is None:
            print("[SERIAL] pyserial 미설치: 비활성화 모드")
            return

        candidate_ports = [port, "/dev/ttyACM0", "/dev/ttyUSB0", "COM7", "COM3"]
        tried = set()

        for p in candidate_ports:
            if p in tried:
                continue
            tried.add(p)
            try:
                self.ser = serial.Serial(p, baudrate, timeout=timeout)
                time.sleep(2.0)
                self.ser.reset_input_buffer()
                print(f"[SERIAL] 연결 성공: {p} ({baudrate}bps)")
                return
            except Exception:
                continue

        print(f"[SERIAL] 연결 실패 ({port}): 단독 테스트 모드")

    def poll_command(self):
        if self.ser is None or not self.ser.is_open:
            return None
        try:
            while self.ser.in_waiting > 0:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if line == "CAPTURE":
                    return "CAPTURE"
                elif line.startswith("["):
                    print(f"[MCU] {line}")
        except Exception as e:
            print(f"[SERIAL] 수신 오류: {e}")
        return None

    def send_result(self, decision: str):
        cmd = "PASS" if decision == "PASS" else "FAIL"
        if self.ser is None or not self.ser.is_open:
            print(f"[SERIAL-MOCK] 결과 송신 생략: {cmd}")
            return False
        try:
            self.ser.write(f"{cmd}\n".encode("ascii"))
            print(f"[SERIAL] 결과 송신: {cmd}")
            return True
        except Exception as e:
            print(f"[SERIAL] 송신 오류 ({cmd}): {e}")
            return False

    def close(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()


class PCBInspector:
    def __init__(self, model_path=None, target_w=400, target_h=800, log_dir=None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if model_path is None:
            model_path = os.path.join(base_dir, "weights", "best.pt")
        if log_dir is None:
            log_dir = os.path.join(base_dir, "logs")

        self.target_w = target_w
        self.target_h = target_h
        self.log_dir = log_dir
        self.inspect_seq = 0

        self.model = None
        if os.path.exists(model_path):
            try:
                self.model = YOLO(model_path)
                print(f"[INIT] YOLO 모델 로드: {model_path}")
            except Exception as e:
                print(f"[WARN] YOLO 로드 오류 ({e}): 고정 ROI 모드 전환")
        else:
            print(f"[WARN] 모델 파일 없음 ({model_path}): 고정 ROI 모드 전환")

        self.class_map = {
            0: "fnd",
            1: "switch",
            2: "ic_chip",
            3: "esp01"
        }

        self.ref_roi_ratios = {
            "esp01":   (0.035, 0.230, 0.220, 0.680),
            "switch":  (0.295, 0.470, 0.240, 0.520),
            "ic_chip": (0.300, 0.555, 0.580, 0.820),
            "fnd":     (0.520, 0.970, 0.130, 0.550),
        }

        self.angle_targets = ["ic_chip", "fnd"]
        self.ANGLE_TOLERANCE = 3.0
        self.OFFSET_TOLERANCE_PX = 12.0
        self.BBOX_PAD = 8

    def order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    def find_board_corners_auto(self, frame):
        # [복구 완료] 검은 테이프 경계를 정확히 잡던 원래 알고리즘
        if frame is None:
            return None

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        main_c = max(contours, key=cv2.contourArea)
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
        # [복구 완료] 이상한 고정 좌표(fallback_corners) 제거, 원래 원근 보정 로직
        pts = self.find_board_corners_auto(frame)
        if pts is None:
            print("[WARN] 보드 외곽선 검출 실패: 원본 프레임 리사이즈 대체")
            warped = cv2.resize(frame, (self.target_w, self.target_h))
        else:
            dst = np.array([
                [0, 0],
                [self.target_w - 1, 0],
                [self.target_w - 1, self.target_h - 1],
                [0, self.target_h - 1]], dtype="float32")
            M = cv2.getPerspectiveTransform(pts, dst)
            warped = cv2.warpPerspective(frame, M, (self.target_w, self.target_h))

        lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        normalized = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

        return normalized

    def get_reference_rois(self, h, w):
        rois = {}
        for name, (ymin_r, ymax_r, xmin_r, xmax_r) in self.ref_roi_ratios.items():
            rois[name] = (int(h * ymin_r), int(h * ymax_r), int(w * xmin_r), int(w * xmax_r))
        return rois

    def detect_and_extract_rois(self, image, conf_thres=0.35):
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
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 85, 255, cv2.THRESH_BINARY_INV)
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
        sub_dir = "pass" if final_decision == "PASS" else "fail"
        save_dir = os.path.join(self.log_dir, sub_dir)
        os.makedirs(save_dir, exist_ok=True)

        self.inspect_seq += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{sub_dir}_{timestamp}_{self.inspect_seq:04d}.jpg"
        rel_path = f"logs/{sub_dir}/{filename}"
        abs_path = os.path.join(save_dir, filename)

        try:
            cv2.imwrite(abs_path, result_img)
            cv2.imwrite("latest_inspection_result.jpg", result_img)
        except Exception as e:
            print(f"[ERROR] 이미지 저장 실패: {e}")

        return rel_path

    def run_unified_inspection(self, warped_img):
        if warped_img is None:
            return None, None

        clean_img = warped_img.copy()
        result_img = warped_img.copy()
        h, w = clean_img.shape[:2]

        ref_rois = self.get_reference_rois(h, w)
        cropped_dict, detected_rois, _ = self.detect_and_extract_rois(clean_img)
        defect_summary = {name: [] for name in self.ref_roi_ratios.keys()}

        print("-" * 55)
        print(f"[INSPECT] 부품 검출 수: {len(cropped_dict)} / {len(self.ref_roi_ratios)}")

        for name, (ry1, ry2, rx1, rx2) in ref_rois.items():
            if name not in cropped_dict:
                defect_summary[name].append("MISSING")
                cv2.rectangle(result_img, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2)
                cv2.putText(result_img, f"{name}: MISSING", (rx1, max(15, ry1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2, cv2.LINE_AA)
                print(f"[FAIL] {name.upper():<8}: MISSING")
                continue

            roi_crop = cropped_dict[name]
            ymin, ymax, xmin, xmax = detected_rois[name]
            logs = []

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

            if name == "esp01":
                esp_status, ratio = self.check_esp01_orientation(roi_crop)
                if esp_status != "PASS":
                    defect_summary[name].append("REVERSE")
                    logs.append(f"역삽불량({ratio:.2f})")
                else:
                    logs.append(f"방향정상({ratio:.2f})")

            comp_defects = defect_summary[name]
            if len(comp_defects) == 0:
                cv2.rectangle(result_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 1)
                cv2.putText(result_img, f"{name}: PASS", (xmin, max(15, ymin - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 200, 0), 1, cv2.LINE_AA)
                print(f"[PASS] {name.upper():<8}: {', '.join(logs)}")
            else:
                if tilt_box is not None:
                    cv2.drawContours(result_img, [tilt_box], 0, (0, 0, 255), 2)
                else:
                    cv2.rectangle(result_img, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)

                err_str = ",".join(comp_defects)
                cv2.putText(result_img, f"{name}: {err_str}", (xmin, max(15, ymin - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1, cv2.LINE_AA)
                print(f"[FAIL] {name.upper():<8}: {err_str} ({', '.join(logs)})")

        total_defects = sum(len(v) for v in defect_summary.values())
        final_decision = "PASS" if total_defects == 0 else "FAIL"

        img_path = self.save_inspection_image(result_img, final_decision)
        inspected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db_record = {
            "final_decision": final_decision,
            "inspected_at": inspected_at,
            "esp01_status": ",".join(defect_summary["esp01"]) if defect_summary["esp01"] else "PASS",
            "ic_chip_status": ",".join(defect_summary["ic_chip"]) if defect_summary["ic_chip"] else "PASS",
            "fnd_status": ",".join(defect_summary["fnd"]) if defect_summary["fnd"] else "PASS",
            "switch_status": ",".join(defect_summary["switch"]) if defect_summary["switch"] else "PASS",
            "img_path": img_path
        }

        print(f"[RESULT] 최종 판정: {final_decision} (불량 {total_defects}건)")
        print("-" * 55)

        return result_img, db_record


def execute_inspection_sequence(cap, inspector, serial_handler=None, db_manager=None, robot_caller=None, triggered_by_mcu=False):
    t_end = time.time() + 0.2
    latest_frame = None
    while time.time() < t_end:
        ret, f = cap.read()
        if ret:
            latest_frame = cv2.flip(f, -1)
        cv2.waitKey(10)

    if latest_frame is None:
        print("[ERROR] 카메라 프레임 읽기 실패")
        if serial_handler is not None:
            serial_handler.send_result("FAIL")
        return None, None

    warped_board = inspector.warp_and_normalize(latest_frame)
    if warped_board is None:
        print("[ERROR] 보드 영역 정규화 실패")
        if serial_handler is not None:
            serial_handler.send_result("FAIL")
        return None, None

    result_img, db_record = inspector.run_unified_inspection(warped_board)

    if serial_handler is not None:
        serial_handler.send_result(db_record["final_decision"])

    if db_manager is not None:
        try:
            db_manager.insert_inspection_result(db_record)
            print("[DB] 검사 결과 저장 완료")
        except Exception as e:
            print(f"[ERROR] DB 저장 실패: {e}")

    if robot_caller is not None:
        try:
            robot_caller(db_record)
        except Exception as e:
            print(f"[ERROR] 로봇 호출 실패: {e}")

    return result_img, db_record