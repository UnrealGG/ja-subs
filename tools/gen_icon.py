"""生成 ja.ico（32 位 BGRA，含 64/48/32 三档），不依赖 Pillow。"""
import io, os, struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

S = 8            # 超采样倍数（相对 64 网格）
BASE = 64
W = BASE * S


def in_round(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render():
    """返回 W×W 的 RGBA 浮点数组（行优先，顶行在前）。"""
    px = [[(0.0, 0.0, 0.0, 0.0)] * W for _ in range(W)]
    for yy in range(W):
        y = yy / S
        t = (y - 2) / 60.0
        t = max(0.0, min(1.0, t))
        br = 0x2E + (0x1A - 0x2E) * t
        bg = 0x80 + (0x5C - 0x80) * t
        bb = 0xFA + (0xC8 - 0xFA) * t
        for xx in range(W):
            x = xx / S
            a = 0.0
            if in_round(x, y, 2, 2, 62, 62, 13):
                a = 1.0
            r, g, b = br, bg, bb
            # 两条白的字幕线
            if in_round(x, y, 12, 23, 52, 31, 4) or in_round(x, y, 12, 37, 40, 45, 4):
                r, g, b = 0xF7, 0xFB, 0xFF
            px[yy][xx] = (r, g, b, a)
    return px


def down(px, size):
    """盒式降采样到 size×size，颜色按 alpha 加权。"""
    step = W // size
    out = []
    for oy in range(size):
        row = []
        for ox in range(size):
            sr = sg = sb = sa = 0.0
            for y in range(oy * step, (oy + 1) * step):
                for x in range(ox * step, (ox + 1) * step):
                    r, g, b, a = px[y][x]
                    sr += r * a
                    sg += g * a
                    sb += b * a
                    sa += a
            n = step * step
            if sa > 0:
                row.append((sr / sa, sg / sa, sb / sa, sa / n))
            else:
                row.append((0.0, 0.0, 0.0, 0.0))
        out.append(row)
    return out


def ico_bytes(images):
    """images: [(size, rows)]，rows 顶行在前。"""
    hdr = struct.pack('<HHH', 0, 1, len(images))
    body = b''
    off = 6 + 16 * len(images)
    entries = b''
    for size, rows in images:
        # BITMAPINFOHEADER
        bi = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                         size * size * 4, 0, 0, 0, 0)
        xor = bytearray()
        for y in range(size - 1, -1, -1):          # BMP 是底行在前
            for x in range(size):
                r, g, b, a = rows[y][x]
                xor += bytes((int(round(b)), int(round(g)), int(round(r)), int(round(a * 255))))
        mask_row = ((size + 31) // 32) * 4
        andm = b'\x00' * (mask_row * size)          # 全 0 = 不透明
        data = bi + bytes(xor) + andm
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), off)
        body += data
        off += len(data)
    return hdr + entries + body


px = render()
imgs = []
for size in (64, 32):
    imgs.append((size, down(px, size)))
io.open(os.path.join(ROOT, 'ja.ico'), 'wb').write(ico_bytes(imgs))
print('ja.ico written')
