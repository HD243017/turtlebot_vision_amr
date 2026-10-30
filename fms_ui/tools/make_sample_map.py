"""시안용 샘플 지도(maps/map.pgm, maps/map.yaml)를 만든다.

실제 맵핑 지도(map_saver 결과)가 생기면 maps/ 의 두 파일을 그것으로 바꾸면 되고,
이 스크립트는 더 쓸 일이 없다.

작업장 3.0 × 2.0 m, 바깥 여백 0.1 m, 해상도 1 cm.
값은 map_saver 규칙을 따른다: 0 = 벽(점유), 254 = 빈 곳, 205 = 모름.
"""
from pathlib import Path

RES = 0.01                 # m / px
ORIGIN = (-0.1, -0.1)      # 지도 왼쪽 아래 모서리의 실제 좌표 (m)
SIZE = (3.2, 2.2)          # 지도 전체 크기 (m)
WALL = 0.03                # 벽 두께 (m)
ROOM = (0.0, 0.0, 3.0, 2.0)          # 작업장 안쪽 (x0, y0, x1, y1)
OBSTACLES = [(1.15, 0.95, 1.85, 1.30)]  # 작업대

OCC, FREE, UNKNOWN = 0, 254, 205


def main():
    w, h = round(SIZE[0] / RES), round(SIZE[1] / RES)
    pix = bytearray([UNKNOWN]) * (w * h)

    def fill(x0, y0, x1, y1, v):
        # 미터 사각형 → 픽셀. PGM은 맨 위 줄이 y 최대
        c0, c1 = round((x0 - ORIGIN[0]) / RES), round((x1 - ORIGIN[0]) / RES)
        r0, r1 = h - round((y1 - ORIGIN[1]) / RES), h - round((y0 - ORIGIN[1]) / RES)
        for r in range(max(r0, 0), min(r1, h)):
            pix[r * w + max(c0, 0): r * w + min(c1, w)] = bytes([v]) * (min(c1, w) - max(c0, 0))

    x0, y0, x1, y1 = ROOM
    fill(x0 - WALL, y0 - WALL, x1 + WALL, y1 + WALL, OCC)
    fill(x0, y0, x1, y1, FREE)
    for o in OBSTACLES:
        fill(*o, OCC)

    out = Path(__file__).resolve().parent.parent / "maps"
    out.mkdir(exist_ok=True)
    (out / "map.pgm").write_bytes(f"P5\n# sample map\n{w} {h}\n255\n".encode() + bytes(pix))
    (out / "map.yaml").write_text(
        "image: map.pgm\n"
        "mode: trinary\n"
        f"resolution: {RES}\n"
        f"origin: [{ORIGIN[0]}, {ORIGIN[1]}, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.25\n",
        encoding="utf-8",
    )
    print(f"maps/map.pgm ({w}x{h}px), maps/map.yaml")


if __name__ == "__main__":
    main()
