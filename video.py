"""MoviePy動画合成モジュール。"""
import io
import math
import re
import tempfile
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    concatenate_videoclips,
)

# 解像度 (YouTube Shorts)
WIDTH = 1080
HEIGHT = 1920

# キャラクター設定
CHARA_BASE_HEIGHT = 700          # キャラ画像の基準高さ (px)
CHARA_ACTIVE_SCALE = 1.05        # 話し中スケール
CHARA_INACTIVE_SCALE = 0.95      # 待機中スケール
CHARA1_X_CENTER = WIDTH // 4     # キャラ1の中心X (左側)
CHARA2_X_CENTER = WIDTH * 3 // 4 # キャラ2の中心X (右側)
CHARA_Y_BOTTOM = HEIGHT - 80     # キャラ底辺のY座標

# 字幕設定
SUBTITLE_Y = 800                 # 字幕上端Y
SUBTITLE_MARGIN = 60             # 字幕左右マージン
SUBTITLE_FONT_SIZE = 52
SUBTITLE_LINE_SPACING = 20
SUBTITLE_BG_ALPHA = 180          # 字幕背景の透明度 (0-255)
SUBTITLE_BG_PADDING = 20

# 背景グラデーション (上: 濃い青、下: 明るい紫)
BG_TOP_COLOR = (20, 10, 60)
BG_BOTTOM_COLOR = (80, 20, 120)

# ボブアニメーション設定
BOB_AMPLITUDE = 12   # 上下の振れ幅 (px)
BOB_FREQUENCY = 3.5  # 1秒あたりのボブ回数 (Hz)

# キャラ1専用アニメーション（手・体の動き）
CHARA1_ROT_AMPLITUDE = 6.0   # 回転の振れ幅 (degrees)
CHARA1_ROT_FREQUENCY = 2.5   # 回転の速さ (Hz)
CHARA1_TALKING_FREQUENCY = 4.0  # 口パク切り替え速度 (Hz)


def _make_gradient_bg() -> np.ndarray:
    """縦型グラデーション背景画像をndarrayで生成。"""
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(BG_TOP_COLOR[0] * (1 - t) + BG_BOTTOM_COLOR[0] * t)
        g = int(BG_TOP_COLOR[1] * (1 - t) + BG_BOTTOM_COLOR[1] * t)
        b = int(BG_TOP_COLOR[2] * (1 - t) + BG_BOTTOM_COLOR[2] * t)
        img[y, :] = [r, g, b]
    return img


def _load_chara_image(path: str, height: int, flip: bool = False) -> Image.Image:
    """キャラ画像をPillowで読み込み、指定高さにリサイズ（アスペクト比維持）。"""
    img = Image.open(path).convert("RGBA")
    ratio = height / img.height
    new_w = int(img.width * ratio)
    img = img.resize((new_w, height), Image.LANCZOS)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img


def _get_font(size: int):
    """フォントを取得。システムフォントがなければPillowのデフォルトを使用。"""
    font_candidates = [
        # macOS
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
        # Linux (Noto CJK - packages.txt でインストール)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ]
    for candidate in font_candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """テキストをmax_width内に折り返す。"""
    lines = []
    current = ""
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    for char in text:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _load_bg_image(path: str) -> np.ndarray:
    """背景画像をアスペクト比を維持して1080x1920にクロップ・リサイズして返す。"""
    img = Image.open(path).convert("RGB")
    src_w, src_h = img.size
    # 縦横それぞれのスケールを計算し、大きい方に合わせてスケール（Coverモード）
    scale = max(WIDTH / src_w, HEIGHT / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # 中央クロップ
    left = (new_w - WIDTH) // 2
    top = (new_h - HEIGHT) // 2
    img = img.crop((left, top, left + WIDTH, top + HEIGHT))
    return np.array(img)


# モジュールレベルでキャッシュ（毎フレーム読み込まないよう）
_bg_cache: np.ndarray | None = None
_bg_cache_path: str | None = None


def set_background(path: str | None) -> None:
    """背景画像をキャッシュにセット。Noneならグラデーションを使用。"""
    global _bg_cache, _bg_cache_path
    if path is None:
        _bg_cache = None
        _bg_cache_path = None
    else:
        _bg_cache = _load_bg_image(path)
        _bg_cache_path = path


def _render_subtitle(text: str, active_chara: str) -> np.ndarray:
    """字幕付きの背景フレームをndarrayで返す。"""
    if _bg_cache is not None:
        bg = Image.fromarray(_bg_cache).convert("RGBA")
    else:
        bg = Image.fromarray(_make_gradient_bg()).convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = _get_font(SUBTITLE_FONT_SIZE)
    max_text_width = WIDTH - SUBTITLE_MARGIN * 2
    lines = _wrap_text(text, font, max_text_width)

    # 各行の高さを計算
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_height = SUBTITLE_FONT_SIZE + SUBTITLE_LINE_SPACING
    total_text_height = line_height * len(lines)

    # 字幕背景矩形
    box_x1 = SUBTITLE_MARGIN - SUBTITLE_BG_PADDING
    box_y1 = SUBTITLE_Y - SUBTITLE_BG_PADDING
    box_x2 = WIDTH - SUBTITLE_MARGIN + SUBTITLE_BG_PADDING
    box_y2 = SUBTITLE_Y + total_text_height + SUBTITLE_BG_PADDING

    draw.rounded_rectangle(
        [box_x1, box_y1, box_x2, box_y2],
        radius=16,
        fill=(0, 0, 0, SUBTITLE_BG_ALPHA),
    )

    # テキスト描画
    for i, line in enumerate(lines):
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (WIDTH - text_w) // 2
        y = SUBTITLE_Y + i * line_height
        # 影
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 200))
        # 本文
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    composite = Image.alpha_composite(bg, overlay)
    return np.array(composite.convert("RGB"))


def _paste_chara(frame: np.ndarray, chara_img: Image.Image, x_center: int, is_active: bool, y_offset: int = 0, rotation: float = 0.0) -> np.ndarray:
    """フレームにキャラ画像を合成する。"""
    scale = CHARA_ACTIVE_SCALE if is_active else CHARA_INACTIVE_SCALE
    target_h = int(CHARA_BASE_HEIGHT * scale)
    ratio = target_h / chara_img.height
    target_w = int(chara_img.width * ratio)
    resized = chara_img.resize((target_w, target_h), Image.LANCZOS)
    if rotation != 0.0:
        resized = resized.rotate(rotation, resample=Image.BICUBIC, expand=False)

    x = x_center - target_w // 2
    y = CHARA_Y_BOTTOM - target_h + y_offset

    # PIL画像に変換して合成
    frame_img = Image.fromarray(frame).convert("RGBA")
    # クリッピング
    paste_x = max(x, 0)
    paste_y = max(y, 0)
    crop_x = paste_x - x
    crop_y = paste_y - y
    crop_w = min(target_w - crop_x, WIDTH - paste_x)
    crop_h = min(target_h - crop_y, HEIGHT - paste_y)
    if crop_w > 0 and crop_h > 0:
        chara_cropped = resized.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        frame_img.paste(chara_cropped, (paste_x, paste_y), chara_cropped)

    return np.array(frame_img.convert("RGB"))


def _split_subtitle_chunks(text: str, max_chars: int = 22) -> list[str]:
    """
    長いテキストを字幕チャンクに分割する。
    句読点（。！？）の後で優先的に分割し、それでもmax_charsを超える場合は強制分割。
    """
    if len(text) <= max_chars:
        return [text]

    # 句読点の後で分割
    parts = [p for p in re.split(r'(?<=[。！？])', text) if p]
    if not parts:
        parts = [text]

    chunks: list[str] = []
    current = ""
    for part in parts:
        if not current:
            current = part
        elif len(current) + len(part) <= max_chars:
            current += part
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)

    # それでも長いチャンクは強制分割
    result: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            result.append(chunk[:max_chars])
            chunk = chunk[max_chars:]
        if chunk:
            result.append(chunk)

    return result if result else [text]


def build_video(
    lines: list[dict],
    chara1_path: str,
    chara2_path: str,
    output_path: str,
    chara1_talking_path: str | None = None,
    bg_path: str | None = None,
    fps: int = 30,
    progress_callback=None,
) -> None:
    """
    動画を合成してMP4ファイルに出力する。

    Args:
        lines: synthesize_lines()の戻り値
              [{"chara": str, "text": str, "audio": bytes, "duration": float}, ...]
        chara1_path: キャラ1画像パス
        chara2_path: キャラ2画像パス
        output_path: 出力MP4パス
        bg_path: 背景画像パス (Noneならグラデーション)
        fps: フレームレート
    """
    set_background(bg_path)
    chara1_img = _load_chara_image(chara1_path, CHARA_BASE_HEIGHT, flip=False)
    chara1_talking_img = _load_chara_image(chara1_talking_path, CHARA_BASE_HEIGHT, flip=False) if chara1_talking_path else chara1_img
    chara2_img = _load_chara_image(chara2_path, CHARA_BASE_HEIGHT, flip=True)

    clips = []
    audio_tmpfiles = []

    total_lines = len(lines)

    try:
        for line_idx, line in enumerate(lines):
            chara = line["chara"]
            text = line["text"]
            duration = line["duration"]
            audio_bytes = line["audio"]

            is_chara1_active = (chara == "chara1")

            if progress_callback:
                progress_callback(line_idx / total_lines, f"動画生成中... {line_idx}/{total_lines} セリフ")

            # 字幕チャンクに分割
            chunks = _split_subtitle_chunks(text)

            def _make_animated_clip(subtitle_bg: np.ndarray, dur: float, is_c1_active: bool) -> VideoClip:
                """ボブアニメーション付きVideoClipを生成する。"""
                def make_frame(t, _sub=subtitle_bg,
                               _c1=chara1_img, _c1t=chara1_talking_img,
                               _c2=chara2_img, _is_c1=is_c1_active):
                    frame = _sub.copy()
                    bob = int(BOB_AMPLITUDE * math.sin(2 * math.pi * BOB_FREQUENCY * t))
                    c1_y = bob if _is_c1 else 0
                    c2_y = 0 if _is_c1 else bob
                    # キャラ1発話中: 口パク（通常↔発話画像を高速切り替え） + 回転アニメーション
                    if _is_c1:
                        talking = math.sin(2 * math.pi * CHARA1_TALKING_FREQUENCY * t) > 0
                        c1_img = _c1t if talking else _c1
                    else:
                        c1_img = _c1
                    c1_rot = CHARA1_ROT_AMPLITUDE * math.sin(2 * math.pi * CHARA1_ROT_FREQUENCY * t) if _is_c1 else 0.0
                    frame = _paste_chara(frame, c1_img, CHARA1_X_CENTER, _is_c1, c1_y, c1_rot)
                    frame = _paste_chara(frame, _c2, CHARA2_X_CENTER, not _is_c1, c2_y)
                    return frame
                return VideoClip(make_frame, duration=dur)

            if len(chunks) == 1:
                subtitle_bg = _render_subtitle(text, chara)
                video_clip = _make_animated_clip(subtitle_bg, duration, is_chara1_active)
            else:
                # チャンクごとにVideoClipを作成し連結（文字数比で時間を配分）
                total_chars = sum(len(c) for c in chunks)
                chunk_clips = []
                for chunk in chunks:
                    chunk_dur = duration * len(chunk) / total_chars
                    subtitle_bg = _render_subtitle(chunk, chara)
                    chunk_clips.append(_make_animated_clip(subtitle_bg, chunk_dur, is_chara1_active))
                video_clip = concatenate_videoclips(chunk_clips)

            # 音声をtmpファイルに書き出し
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(audio_bytes)
            tmp.flush()
            tmp.close()
            audio_tmpfiles.append(tmp.name)

            audio_clip = AudioFileClip(tmp.name)
            video_clip = video_clip.with_audio(audio_clip)
            clips.append(video_clip)

        final = concatenate_videoclips(clips, method="compose")

        final.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile="temp_audio.m4a",
            remove_temp=True,
            logger=None,
        )

    finally:
        for path in audio_tmpfiles:
            try:
                os.unlink(path)
            except Exception:
                pass
