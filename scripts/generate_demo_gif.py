#!/usr/bin/env python3
"""Generate a demo GIF showing session-zoo workflow."""

from PIL import Image, ImageDraw, ImageFont
import os

# --- Config ---
WIDTH = 800
LINE_HEIGHT = 22
PADDING = 20
FONT_SIZE = 16
BG_COLOR = (30, 30, 30)          # dark terminal bg
TEXT_COLOR = (204, 204, 204)      # normal text
PROMPT_COLOR = (80, 250, 123)    # green prompt
CMD_COLOR = (255, 255, 255)      # white command
HEADER_COLOR = (139, 233, 253)   # cyan headers
DIM_COLOR = (130, 130, 130)      # dimmed text
ACCENT_COLOR = (255, 184, 108)   # orange accents
SUCCESS_COLOR = (80, 250, 123)   # green success
FRAME_DURATION = 2800            # ms per frame

# Try to find a monospace font
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
]

font = None
for fp in FONT_PATHS:
    if os.path.exists(fp):
        font = ImageFont.truetype(fp, FONT_SIZE)
        break
if font is None:
    font = ImageFont.load_default()

# Each frame: list of (text, color) lines
FRAMES = [
    # Frame 1: Title
    {
        "title": "session-zoo Demo",
        "lines": [
            ("", TEXT_COLOR),
            ("  Save and sync your AI development", TEXT_COLOR),
            ("  sessions to GitHub.", TEXT_COLOR),
            ("", TEXT_COLOR),
            ("  Supports: Claude Code, Codex, and more", DIM_COLOR),
            ("", TEXT_COLOR),
            ("  pip install session-zoo", ACCENT_COLOR),
        ],
    },
    # Frame 2: init
    {
        "title": "Step 1: Initialize",
        "lines": [
            ("$ zoo init", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Created config: ~/.session-zoo/config.toml", SUCCESS_COLOR),
            ("Created index:  ~/.session-zoo/index.db", SUCCESS_COLOR),
            ("", TEXT_COLOR),
            ("$ zoo config set repo git@github.com:user/sessions.git", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Set repo = git@github.com:user/sessions.git", SUCCESS_COLOR),
        ],
    },
    # Frame 3: import
    {
        "title": "Step 2: Import Sessions",
        "lines": [
            ("$ zoo import", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Scanning ~/.claude/projects/ ...", DIM_COLOR),
            ("", TEXT_COLOR),
            ("Imported 12 new sessions:", SUCCESS_COLOR),
            ("  + my-webapp       (5 sessions)", TEXT_COLOR),
            ("  + api-server      (4 sessions)", TEXT_COLOR),
            ("  + cli-tool        (3 sessions)", TEXT_COLOR),
        ],
    },
    # Frame 4: list
    {
        "title": "Step 3: Browse Sessions",
        "lines": [
            ("$ zoo list --project my-webapp", CMD_COLOR),
            ("", TEXT_COLOR),
            ("ID         Project     Tool        Date        Tokens", HEADER_COLOR),
            ("---------- ----------- ----------- ----------  ------", DIM_COLOR),
            ("a1b2c3d4.. my-webapp   claude-code 2026-03-13  45,200", TEXT_COLOR),
            ("e5f6g7h8.. my-webapp   claude-code 2026-03-12  12,800", TEXT_COLOR),
            ("i9j0k1l2.. my-webapp   claude-code 2026-03-11  28,350", TEXT_COLOR),
            ("m3n4o5p6.. my-webapp   claude-code 2026-03-10   8,900", TEXT_COLOR),
            ("q7r8s9t0.. my-webapp   claude-code 2026-03-09  15,600", TEXT_COLOR),
        ],
    },
    # Frame 5: show
    {
        "title": "Step 4: View Details",
        "lines": [
            ("$ zoo show a1b2c3d4", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Session:  a1b2c3d4-5678-9abc-def0-123456789abc", HEADER_COLOR),
            ("Tool:     claude-code", TEXT_COLOR),
            ("Project:  my-webapp", TEXT_COLOR),
            ("Started:  2026-03-13 09:15:00", TEXT_COLOR),
            ("Ended:    2026-03-13 11:42:30", TEXT_COLOR),
            ("Tokens:   45,200", TEXT_COLOR),
            ("Messages: 68", TEXT_COLOR),
            ("Tags:     feature, auth", ACCENT_COLOR),
        ],
    },
    # Frame 6: summarize
    {
        "title": "Step 5: AI Summarize",
        "lines": [
            ("$ zoo summarize a1b2c3d4", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Using provider: claude-code (auto-detected)", DIM_COLOR),
            ("Generating summary...", DIM_COLOR),
            ("", TEXT_COLOR),
            ("Summary saved:", SUCCESS_COLOR),
            ("  Implemented JWT auth with refresh tokens.", TEXT_COLOR),
            ("  Added login/logout endpoints and middleware.", TEXT_COLOR),
            ("  Wrote 12 tests, all passing.", TEXT_COLOR),
        ],
    },
    # Frame 7: tag
    {
        "title": "Step 6: Organize with Tags",
        "lines": [
            ("$ zoo tag a1b2c3d4 feature auth", CMD_COLOR),
            ("Added tags: feature, auth", SUCCESS_COLOR),
            ("", TEXT_COLOR),
            ("$ zoo tags", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Tag        Count", HEADER_COLOR),
            ("---------- -----", DIM_COLOR),
            ("feature        5", TEXT_COLOR),
            ("bugfix         3", TEXT_COLOR),
            ("auth           2", TEXT_COLOR),
            ("refactor       2", TEXT_COLOR),
        ],
    },
    # Frame 8: sync
    {
        "title": "Step 7: Sync to GitHub",
        "lines": [
            ("$ zoo sync", CMD_COLOR),
            ("", TEXT_COLOR),
            ("Syncing 12 sessions to GitHub...", DIM_COLOR),
            ("  raw/claude-code/my-webapp/a1b2c3d4.jsonl", TEXT_COLOR),
            ("  raw/claude-code/my-webapp/a1b2c3d4.meta.json", TEXT_COLOR),
            ("  sessions/my-webapp/2026-03-13/a1b2c3d4.md", TEXT_COLOR),
            ("  ... (9 more)", DIM_COLOR),
            ("", TEXT_COLOR),
            ("Pushed to git@github.com:user/sessions.git", SUCCESS_COLOR),
            ("12 sessions synced successfully!", SUCCESS_COLOR),
        ],
    },
    # Frame 9: restore
    {
        "title": "Cross-Device Restore",
        "lines": [
            ("# On a new machine:", DIM_COLOR),
            ("", TEXT_COLOR),
            ("$ zoo clone", CMD_COLOR),
            ("Cloned session repo to ~/.session-zoo/repo", SUCCESS_COLOR),
            ("", TEXT_COLOR),
            ("$ zoo reindex", CMD_COLOR),
            ("Rebuilt index: 12 sessions", SUCCESS_COLOR),
            ("", TEXT_COLOR),
            ("$ zoo restore", CMD_COLOR),
            ("Restored 12 .jsonl files to ~/.claude/", SUCCESS_COLOR),
            ("Ready to use /resume in Claude Code!", SUCCESS_COLOR),
        ],
    },
]


def render_frame(frame_data: dict) -> Image.Image:
    """Render a single frame as a terminal-style image."""
    title = frame_data["title"]
    lines = frame_data["lines"]

    # Calculate height
    content_lines = len(lines)
    # title bar + gap + content + bottom padding
    height = PADDING + LINE_HEIGHT + 10 + (content_lines * LINE_HEIGHT) + PADDING + 10

    img = Image.new("RGB", (WIDTH, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title bar background
    draw.rectangle([0, 0, WIDTH, PADDING + LINE_HEIGHT + 5], fill=(45, 45, 45))

    # Window controls (circles)
    y_circles = PADDING // 2 + 5
    draw.ellipse([12, y_circles, 24, y_circles + 12], fill=(255, 95, 86))
    draw.ellipse([32, y_circles, 44, y_circles + 12], fill=(255, 189, 46))
    draw.ellipse([52, y_circles, 64, y_circles + 12], fill=(39, 201, 63))

    # Title text centered
    bbox = draw.textbbox((0, 0), title, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((WIDTH - tw) // 2, y_circles - 2), title, fill=TEXT_COLOR, font=font)

    # Content
    y = PADDING + LINE_HEIGHT + 15
    for text, color in lines:
        if text:
            draw.text((PADDING, y), text, fill=color, font=font)
        y += LINE_HEIGHT

    # Subtle border
    draw.rectangle([0, 0, WIDTH - 1, height - 1], outline=(60, 60, 60))

    return img


def main():
    frames = []
    max_height = 0

    # Render all frames
    for fd in FRAMES:
        img = render_frame(fd)
        frames.append(img)
        if img.height > max_height:
            max_height = img.height

    # Normalize all frames to same height
    normalized = []
    for img in frames:
        if img.height < max_height:
            new_img = Image.new("RGB", (WIDTH, max_height), BG_COLOR)
            new_img.paste(img, (0, 0))
            # Redraw border
            draw = ImageDraw.Draw(new_img)
            draw.rectangle([0, 0, WIDTH - 1, max_height - 1], outline=(60, 60, 60))
            normalized.append(new_img)
        else:
            normalized.append(img)

    # Save GIF
    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "demo.gif")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    normalized[0].save(
        out_path,
        save_all=True,
        append_images=normalized[1:],
        duration=FRAME_DURATION,
        loop=0,
        optimize=True,
    )
    print(f"Generated: {out_path}")
    print(f"Frames: {len(normalized)}, Size: {WIDTH}x{max_height}")
    print(f"Duration: {FRAME_DURATION}ms per frame, {len(normalized) * FRAME_DURATION / 1000:.0f}s total")


if __name__ == "__main__":
    main()
