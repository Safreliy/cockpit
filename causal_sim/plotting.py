from __future__ import annotations

import struct
import zlib
from pathlib import Path

from causal_sim.models import TelemetryPoint


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(path: Path, pixels: list[bytearray], width: int, height: int) -> None:
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    data = b"\x89PNG\r\n\x1a\n"
    data += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _chunk(b"IDAT", zlib.compress(raw, 9))
    data += _chunk(b"IEND", b"")
    path.write_bytes(data)


def save_line_chart(telemetry: list[TelemetryPoint], metric: str, path: str | Path) -> None:
    width, height = 640, 280
    margin = 28
    pixels = [bytearray([255, 255, 255] * width) for _ in range(height)]
    values = [point.metrics[metric] for point in telemetry]
    lo, hi = min(values), max(values)
    span = max(hi - lo, 1.0)

    def set_px(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            idx = x * 3
            pixels[y][idx : idx + 3] = bytes(color)

    for x in range(margin, width - margin):
        set_px(x, height - margin, (210, 210, 210))
    for y in range(margin, height - margin):
        set_px(margin, y, (210, 210, 210))

    coords: list[tuple[int, int]] = []
    for idx, value in enumerate(values):
        x = margin + round(idx * (width - 2 * margin - 1) / (len(values) - 1))
        y = height - margin - round((value - lo) * (height - 2 * margin - 1) / span)
        coords.append((x, y))
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            x = round(x1 + (x2 - x1) * step / steps)
            y = round(y1 + (y2 - y1) * step / steps)
            set_px(x, y, (22, 96, 167))
            set_px(x, y + 1, (22, 96, 167))
    _write_png(Path(path), pixels, width, height)

