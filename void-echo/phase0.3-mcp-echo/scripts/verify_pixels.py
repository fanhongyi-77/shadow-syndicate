#!/usr/bin/env python3
"""客观验尺子：从 PNG 像素反解三重信号，与日志真值比对。"""
import base64, struct, sys, zlib
sys.path.insert(0, "src")
from void_echo_test.png import ACCENTS, HEIGHT, PX0, PX1, PY0, PY1, WIDTH, render_frame


def decode(png: bytes):
    i, w, h, idat = 8, 0, 0, b""
    while i < len(png):
        ln = struct.unpack(">I", png[i:i+4])[0]; tag = png[i+4:i+8]; body = png[i+8:i+8+ln]
        if tag == b"IHDR": w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT": idat += body
        i += 12 + ln
    d = zlib.decompress(idat); s = w*3; out = bytearray()
    for y in range(h):
        o = y*(s+1); assert d[o] == 0; out += d[o+1:o+1+s]
    return w, h, out


def px(buf, w, x, y):
    o = (y*w + x)*3; return tuple(buf[o:o+3])


def close(a, b, tol=12):
    return all(abs(u-v) <= tol for u, v in zip(a, b))


def read_signals(png):
    w, h, buf = decode(png)
    # 1) 颜色：在像素里数每种调色板色，取最多者
    tally = {name: 0 for name in ACCENTS}
    for y in range(0, 60):
        for x in range(w):
            c = px(buf, w, x, y)
            for name, rgb in ACCENTS.items():
                if close(c, rgb, 30):
                    tally[name] += 1
    colour = max(tally, key=tally.get) if max(tally.values()) > 0 else "none"
    # 2) 条数：在 y=25 扫描该颜色的连续段
    rgb = ACCENTS.get(colour, ACCENTS["teal"])
    runs, in_run = 0, False
    for x in range(w):
        hit = close(px(buf, w, x, 25), rgb, 30)
        if hit and not in_run: runs += 1; in_run = True
        elif not hit: in_run = False
    # 3) 斜线方向：三条候选线段上 DARK 像素占比，取最高
    def score(a, b):
        n, hit = 60, 0
        for k in range(n):
            t = k/(n-1)
            x = int(a[0] + (b[0]-a[0])*t); y = int(a[1] + (b[1]-a[1])*t)
            if close(px(buf, w, x, y), (25, 25, 35), 40): hit += 1
        return hit/n
    my = (PY0+PY1)/2
    cand = {"backslash": score((PX0, PY0), (PX1, PY1)),
            "slash": score((PX0, PY1), (PX1, PY0)),
            "horizontal": score((PX0, my), (PX1, my))}
    direction = max(cand, key=cand.get)
    return runs, colour, direction, round(cand[direction], 2)


if __name__ == "__main__":
    print("  期望(渲染参数)          →  实测(像素反解)")
    bad = 0
    for count in (1, 2, 3):
        for colour in ACCENTS:
            for direction in ("backslash", "slash", "horizontal"):
                got = read_signals(render_frame(0, count, colour, direction))
                ok = got[0] == count and got[1] == colour and got[2] == direction
                bad += 0 if ok else 1
                if not ok:
                    print(f"   [BAD] {count}/{colour}/{direction} → {got}")
    print(f"  54 组全组合校验：{'✅ 全部一致' if bad == 0 else f'❌ {bad} 组不符'}")
    sys.exit(1 if bad else 0)
