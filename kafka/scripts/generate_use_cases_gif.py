#!/usr/bin/env python3
"""Generate a sketchbook-style animated GIF of 10 Kafka use cases."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "kafka-use-cases-animated.gif"
W, H = 900, 1200
BG = (250, 248, 242)
INK = (40, 40, 45)
BLUE = (37, 99, 180)
GREEN = (34, 140, 90)
ORANGE = (210, 110, 40)
PURPLE = (120, 70, 170)
CARD = (255, 255, 255)
LINE = (220, 215, 200)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

USE_CASES = [
    {
        "n": 1,
        "title": "Async Messaging",
        "blurb": "Decouple producers from consumers.\nAbsorb spikes without dropping work.",
        "flow": ["API / Service", "Kafka topic", "Worker"],
        "color": BLUE,
        "tag": "decouple + buffer",
    },
    {
        "n": 2,
        "title": "Pub-Sub Fan-Out",
        "blurb": "One event, many independent consumers.\nEmail, billing, analytics — all at once.",
        "flow": ["order.placed", "Email", "Billing", "Analytics"],
        "color": PURPLE,
        "tag": "1 → N consumer groups",
    },
    {
        "n": 3,
        "title": "Activity Tracking",
        "blurb": "Clicks, views, searches → durable stream.\nLinkedIn’s original Kafka use case.",
        "flow": ["User actions", "activity topic", "Dashboards / ML"],
        "color": GREEN,
        "tag": "high-volume events",
    },
    {
        "n": 4,
        "title": "Log Aggregation",
        "blurb": "Ship logs from every service into Kafka.\nCentralize before Elastic / S3 / Pinot.",
        "flow": ["svc logs", "logs topic", "Search / lake"],
        "color": ORANGE,
        "tag": "durable log buffer",
    },
    {
        "n": 5,
        "title": "Stream Processing",
        "blurb": "Filter, join, window, enrich in flight.\nStreams / Flink / ksqlDB → new topics.",
        "flow": ["raw events", "Flink / Streams", "derived topics"],
        "color": BLUE,
        "tag": "transform in motion",
    },
    {
        "n": 6,
        "title": "Metrics & Alerting",
        "blurb": "Continuous metrics into Kafka.\nDetect anomalies and fire alerts fast.",
        "flow": ["metrics", "metrics topic", "Alerting"],
        "color": ORANGE,
        "tag": "observability backbone",
    },
    {
        "n": 7,
        "title": "Event Sourcing",
        "blurb": "State = replay of immutable events.\nAudit trail + rebuild projections anytime.",
        "flow": ["commands", "event log", "projections"],
        "color": PURPLE,
        "tag": "log as source of truth",
    },
    {
        "n": 8,
        "title": "Change Data Capture",
        "blurb": "DB inserts/updates/deletes → stream.\nDebezium keeps caches & search in sync.",
        "flow": ["DB binlog", "CDC topic", "cache / ES / lake"],
        "color": GREEN,
        "tag": "Debezium → Kafka",
    },
    {
        "n": 9,
        "title": "Data Pipelines",
        "blurb": "Move operational data to warehouses.\nConnect sinks: S3, Snowflake, BigQuery.",
        "flow": ["OLTP / apps", "Kafka", "Warehouse"],
        "color": BLUE,
        "tag": "integration bus",
    },
    {
        "n": 10,
        "title": "Replay & Recovery",
        "blurb": "Rewind to any offset and reprocess.\nFix bugs, rebuild state, recover safely.",
        "flow": ["retained log", "reset offset", "reprocess"],
        "color": ORANGE,
        "tag": "time-travel the log",
    },
]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def ruled_bg() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(70, H, 28):
        d.line([(40, y), (W - 40, y)], fill=LINE, width=1)
    # left margin rule
    d.line([(70, 40), (70, H - 40)], fill=(230, 180, 180), width=2)
    return img


def round_rect(d: ImageDraw.ImageDraw, xy, fill, outline, width=3, radius=22):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_header(d: ImageDraw.ImageDraw, subtitle: str):
    d.text((90, 48), "10 Kafka Use Cases", font=font(FONT_BOLD, 42), fill=BLUE)
    d.text((90, 100), subtitle, font=font(FONT_REG, 20), fill=INK)


def draw_progress(d: ImageDraw.ImageDraw, active: int, total: int = 10):
    start_x = 90
    y = H - 70
    gap = 28
    for i in range(total):
        x = start_x + i * gap
        r = 8
        if i + 1 == active:
            d.ellipse([x - r, y - r, x + r, y + r], fill=BLUE)
        else:
            d.ellipse([x - r, y - r, x + r, y + r], outline=BLUE, width=2)
    d.text((start_x + total * gap + 10, y - 12), f"{active}/{total}", font=font(FONT_MONO, 18), fill=INK)


def draw_mini_flow(d: ImageDraw.ImageDraw, items: list[str], color, top: int):
    """Draw a simple left-to-right or fan-out flow inside the card."""
    if len(items) == 4 and items[0].endswith(".placed") or (len(items) == 4 and "order" in items[0].lower()):
        # fan-out: one source → three sinks
        src = items[0]
        sinks = items[1:]
        cx, cy = W // 2, top + 40
        round_rect(d, (cx - 110, cy - 28, cx + 110, cy + 28), (245, 245, 255), color, 3, 16)
        d.text((cx - 90, cy - 12), src, font=font(FONT_MONO, 18), fill=color)
        for i, s in enumerate(sinks):
            x = 140 + i * 220
            y = top + 140
            d.line([(cx, cy + 28), (x + 70, y - 8)], fill=color, width=3)
            round_rect(d, (x, y - 24, x + 160, y + 28), CARD, color, 2, 14)
            d.text((x + 18, y - 8), s, font=font(FONT_REG, 18), fill=INK)
        return

    # linear 3-box flow
    boxes = items[:3]
    xs = [120, 370, 620]
    y = top + 70
    for i, (x, label) in enumerate(zip(xs, boxes)):
        round_rect(d, (x, y - 36, x + 170, y + 36), CARD, color, 3, 16)
        # center-ish text
        tw = d.textlength(label, font=font(FONT_REG, 18))
        d.text((x + (170 - tw) / 2, y - 10), label, font=font(FONT_REG, 18), fill=INK)
        if i < len(boxes) - 1:
            d.line([(x + 170, y), (xs[i + 1], y)], fill=color, width=3)
            d.polygon(
                [(xs[i + 1] - 2, y), (xs[i + 1] - 14, y - 8), (xs[i + 1] - 14, y + 8)],
                fill=color,
            )


def frame_title() -> Image.Image:
    img = ruled_bg()
    d = ImageDraw.Draw(img)
    draw_header(d, "every developer should know  ·  sketchbook reel")

    round_rect(d, (90, 180, W - 90, 780), CARD, BLUE, 4, 28)
    d.text((130, 230), "Apache Kafka", font=font(FONT_BOLD, 48), fill=BLUE)
    d.text((130, 300), "is everywhere.", font=font(FONT_BOLD, 40), fill=INK)
    d.text(
        (130, 380),
        "From async messaging to CDC,\nfan-out, stream processing,\nand replayable recovery.",
        font=font(FONT_REG, 28),
        fill=INK,
        spacing=10,
    )

    # floating chips
    chips = [
        (130, 560, "durable log", GREEN),
        (340, 560, "fan-out", PURPLE),
        (520, 560, "replay", ORANGE),
    ]
    for x, y, text, c in chips:
        round_rect(d, (x, y, x + 160, y + 56), (255, 255, 255), c, 3, 18)
        d.text((x + 22, y + 16), text, font=font(FONT_BOLD, 20), fill=c)

    d.text((130, 680), "Swipe the frames →", font=font(FONT_REG, 24), fill=BLUE)
    start_x, y = 90, H - 70
    for i in range(10):
        x = start_x + i * 28
        d.ellipse([x - 8, y - 8, x + 8, y + 8], outline=BLUE, width=2)
    d.text((start_x + 10 * 28 + 10, y - 12), "intro", font=font(FONT_MONO, 18), fill=INK)
    return img


def frame_use_case(uc: dict) -> Image.Image:
    img = ruled_bg()
    d = ImageDraw.Draw(img)
    draw_header(d, "durable log  ·  fan-out  ·  replay")

    color = uc["color"]
    # number badge
    d.ellipse([95, 160, 175, 240], fill=color)
    num = str(uc["n"])
    d.text((118 if uc["n"] < 10 else 108, 178), num, font=font(FONT_BOLD, 36), fill=(255, 255, 255))

    d.text((200, 175), uc["title"], font=font(FONT_BOLD, 40), fill=color)
    round_rect(d, (200, 235, 200 + 280, 275), (255, 255, 255), color, 2, 14)
    d.text((215, 243), uc["tag"], font=font(FONT_MONO, 16), fill=color)

    # blurb card
    round_rect(d, (90, 310, W - 90, 500), CARD, color, 3, 24)
    d.text((120, 350), uc["blurb"], font=font(FONT_REG, 26), fill=INK, spacing=12)

    # flow card
    round_rect(d, (90, 530, W - 90, 820), (252, 252, 248), color, 3, 24)
    d.text((120, 555), "mini flow", font=font(FONT_BOLD, 22), fill=color)
    draw_mini_flow(d, uc["flow"], color, 600)

    # sticky
    sticky = (255, 248, 200)
    round_rect(d, (90, 850, 520, 980), sticky, ORANGE, 2, 16)
    d.text((115, 880), "Why Kafka fits:", font=font(FONT_BOLD, 20), fill=ORANGE)
    d.text(
        (115, 915),
        "retain · multiple consumers · rewind",
        font=font(FONT_REG, 20),
        fill=INK,
    )

    draw_progress(d, uc["n"])
    return img


def frame_outro() -> Image.Image:
    img = ruled_bg()
    d = ImageDraw.Draw(img)
    draw_header(d, "one platform, many patterns")

    round_rect(d, (90, 180, W - 90, 900), CARD, GREEN, 4, 28)
    d.text((130, 230), "Key idea", font=font(FONT_BOLD, 36), fill=GREEN)
    d.text(
        (130, 300),
        "Kafka is a distributed,\nreplayable commit log.\n\n"
        "That single abstraction unlocks\nmessaging, CDC, pipelines,\nevent sourcing, and recovery.",
        font=font(FONT_REG, 28),
        fill=INK,
        spacing=10,
    )
    d.text((130, 620), "See detailed notes:", font=font(FONT_BOLD, 22), fill=BLUE)
    d.text(
        (130, 665),
        "kafka/03-use-cases-and-real-life-examples.md",
        font=font(FONT_MONO, 18),
        fill=INK,
    )
    d.text((130, 740), "solid-goggles  ·  sketchbook notes", font=font(FONT_REG, 22), fill=PURPLE)

    start_x, y = 90, H - 70
    for i in range(10):
        x = start_x + i * 28
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=GREEN)
    d.text((start_x + 10 * 28 + 10, y - 12), "done", font=font(FONT_MONO, 18), fill=INK)
    return img


def main():
    frames: list[Image.Image] = [frame_title()]
    for uc in USE_CASES:
        frames.append(frame_use_case(uc))
    frames.append(frame_outro())

    # durations: title longer, each use case ~1.6s, outro longer
    durations = [2200] + [1600] * len(USE_CASES) + [2400]

    # Optimize palette for smaller GIF
    quantized = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    quantized[0].save(
        OUT,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT} ({size_mb:.2f} MiB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
