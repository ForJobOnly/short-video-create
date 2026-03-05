"""ゆっくり実況風YouTubeショート動画自動生成ツール CLI エントリポイント。"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# スクリプトのあるディレクトリを基準にする（VS Code等どこから実行しても動く）
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from tts import load_reading_list, synthesize_lines
from video import build_video


def parse_script(script_path: str) -> list[dict]:
    """
    原稿ファイルをパースして行リストを返す。

    フォーマット:
        [キャラ1] セリフ
        [キャラ2] セリフ

    Returns:
        [{"chara": "chara1" | "chara2", "text": str}, ...]
    """
    pattern = re.compile(r"^\[キャラ([12])\]\s*(.+)$")
    lines = []
    with open(script_path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            m = pattern.match(raw)
            if not m:
                print(f"警告: {lineno}行目をスキップ (フォーマット不一致): {raw!r}", file=sys.stderr)
                continue
            chara_num = m.group(1)
            text = m.group(2).strip()
            lines.append({"chara": f"chara{chara_num}", "text": text})
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ゆっくり実況風YouTubeショート動画を自動生成します。"
    )
    parser.add_argument("--chara1", default=str(BASE_DIR / "input/chara1.png"), help="キャラ1画像パス")
    parser.add_argument("--chara2", default=str(BASE_DIR / "input/chara2.png"), help="キャラ2画像パス")
    parser.add_argument("--script", default=str(BASE_DIR / "input/script.txt"), help="原稿テキストファイルパス")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parser.add_argument("--output", default=str(BASE_DIR / f"output_{timestamp}.mp4"), help="出力MP4ファイルパス")
    # input/bg.png があれば自動で使う
    default_bg = BASE_DIR / "input" / "bg.png"
    parser.add_argument(
        "--background",
        default=str(default_bg) if default_bg.exists() else None,
        help="背景画像パス (省略時: input/bg.png があれば自動使用、なければグラデーション)"
    )
    parser.add_argument(
        "--voice1", default=None,
        help="キャラ1のGoogle Cloud TTS 声名 (デフォルト: ja-JP-Neural2-B)"
    )
    parser.add_argument(
        "--voice2", default=None,
        help="キャラ2のGoogle Cloud TTS 声名 (デフォルト: ja-JP-Neural2-D)"
    )
    default_reading_list = BASE_DIR / "input" / "reading_list.txt"
    parser.add_argument(
        "--reading-list",
        default=str(default_reading_list) if default_reading_list.exists() else None,
        help="読み方変換リストファイルパス (省略時: input/reading_list.txt があれば自動使用)",
    )
    args = parser.parse_args()

    # 原稿パース
    print(f"原稿を読み込み中: {args.script}")
    lines = parse_script(args.script)
    if not lines:
        print("エラー: 有効なセリフが見つかりませんでした。", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(lines)} 行のセリフを検出")

    # 声設定
    voice_configs = {}
    if args.voice1 is not None:
        voice_configs["chara1"] = {"name": args.voice1, "speaking_rate": 0.95, "pitch": -2.0}
    if args.voice2 is not None:
        voice_configs["chara2"] = {"name": args.voice2, "speaking_rate": 1.05, "pitch": 1.0}

    # 読み方変換リスト読み込み
    reading_list = None
    if args.reading_list:
        reading_list = load_reading_list(args.reading_list)
        print(f"読み方変換リスト: {args.reading_list} ({len(reading_list)} 件)")

    # TTS音声合成
    print("Google Cloud TTSで音声合成中...")
    try:
        synthesized = synthesize_lines(lines, voice_configs or None, reading_list)
    except Exception as e:
        print(f"エラー: 音声合成に失敗しました。GOOGLE_APPLICATION_CREDENTIALSを確認してください。\n  {e}", file=sys.stderr)
        sys.exit(1)

    total_duration = sum(s["duration"] for s in synthesized)
    print(f"  合計音声時間: {total_duration:.1f}秒")

    # 動画合成
    print(f"動画を合成中: {args.output}")
    if args.background:
        print(f"  背景画像: {args.background}")
    try:
        build_video(
            lines=synthesized,
            chara1_path=args.chara1,
            chara2_path=args.chara2,
            output_path=args.output,
            bg_path=args.background,
        )
    except Exception as e:
        print(f"エラー: 動画合成に失敗しました。\n  {e}", file=sys.stderr)
        sys.exit(1)

    print(f"完了! 出力ファイル: {args.output}")


if __name__ == "__main__":
    main()
