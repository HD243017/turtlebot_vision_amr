"""지도(map_saver 결과)와 구역 설정을 읽어 화면에 넘길 형태로 만든다.

- maps/ 의 지도 yaml(기본 maps/map_test1.yaml) + 그 안의 image(.pgm 또는 .png)를 읽는다.
- 브라우저는 .pgm을 못 열므로 PNG로 바꾼다. 이때 색을 칠하지 않고
  "벽 = 흰색 불투명, 모름 = 흰색 반투명, 빈 곳 = 투명" 마스크로 만들어,
  화면 쪽 CSS가 테마(다크 · 라이트 · 발표 모드)에 맞는 색을 입히게 한다.
- config/zones.yaml 의 구역 · 마커 · 목표 좌표를 그대로 넘긴다 (단위 m).
"""
import io
from pathlib import Path

import yaml
from PIL import Image

UNKNOWN_ALPHA = 40   # 모름 영역을 얼마나 진하게 보일지 (0~255)


def load_map(yaml_path):
    """map.yaml을 읽어 (meta, png_bytes)를 돌려준다. 파일이 없으면 (None, None)."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return None, None
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    img = Image.open(yaml_path.parent / cfg["image"]).convert("L")

    negate = int(cfg.get("negate", 0))
    occ_th = float(cfg.get("occupied_thresh", 0.65))
    free_th = float(cfg.get("free_thresh", 0.25))

    # map_server와 같은 판정: 점유 확률 p = (255 - v) / 255 (negate면 v / 255)
    def alpha(v):
        p = v / 255 if negate else (255 - v) / 255
        if p > occ_th:
            return 255
        if p < free_th:
            return 0
        return UNKNOWN_ALPHA

    a = img.point([alpha(v) for v in range(256)])
    mask = Image.merge("LA", (Image.new("L", img.size, 255), a))
    buf = io.BytesIO()
    mask.save(buf, format="PNG")

    res = float(cfg["resolution"])
    w, h = img.size
    meta = {
        "resolution": res,
        "origin": [float(cfg["origin"][0]), float(cfg["origin"][1])],
        "width_m": round(w * res, 4),
        "height_m": round(h * res, 4),
        "px": [w, h],
    }
    return meta, buf.getvalue()


def load_zones(path):
    path = Path(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    cfg = cfg or {}
    return {
        "zones": cfg.get("zones") or [],
        "labels": cfg.get("labels") or [],
    }
