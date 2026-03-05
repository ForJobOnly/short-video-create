"""Streamlit Web UI for short video generation."""
import io
import sys
import tempfile
import os
import wave
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from main import parse_script
from tts import load_reading_list, synthesize, VOICE_CONFIGS
from video import build_video

st.set_page_config(page_title="ショート動画生成", page_icon="🎬", layout="centered")
st.title("🎬 ショート動画自動生成")

VOICE_OPTIONS = {
    "✨ Chirp3-HD（最高品質）女性": [
        "ja-JP-Chirp3-HD-Achernar", "ja-JP-Chirp3-HD-Aoede", "ja-JP-Chirp3-HD-Autonoe",
        "ja-JP-Chirp3-HD-Callirrhoe", "ja-JP-Chirp3-HD-Despina", "ja-JP-Chirp3-HD-Erinome",
        "ja-JP-Chirp3-HD-Gacrux", "ja-JP-Chirp3-HD-Kore", "ja-JP-Chirp3-HD-Laomedeia",
        "ja-JP-Chirp3-HD-Leda", "ja-JP-Chirp3-HD-Pulcherrima", "ja-JP-Chirp3-HD-Sulafat",
        "ja-JP-Chirp3-HD-Vindemiatrix", "ja-JP-Chirp3-HD-Zephyr",
    ],
    "✨ Chirp3-HD（最高品質）男性": [
        "ja-JP-Chirp3-HD-Achird", "ja-JP-Chirp3-HD-Algenib", "ja-JP-Chirp3-HD-Algieba",
        "ja-JP-Chirp3-HD-Alnilam", "ja-JP-Chirp3-HD-Charon", "ja-JP-Chirp3-HD-Enceladus",
        "ja-JP-Chirp3-HD-Fenrir", "ja-JP-Chirp3-HD-Iapetus", "ja-JP-Chirp3-HD-Orus",
        "ja-JP-Chirp3-HD-Puck", "ja-JP-Chirp3-HD-Rasalgethi", "ja-JP-Chirp3-HD-Sadachbia",
        "ja-JP-Chirp3-HD-Sadaltager", "ja-JP-Chirp3-HD-Schedar", "ja-JP-Chirp3-HD-Umbriel",
        "ja-JP-Chirp3-HD-Zubenelgenubi",
    ],
    "Neural2（高品質）": [
        "ja-JP-Neural2-B", "ja-JP-Neural2-C", "ja-JP-Neural2-D",
    ],
    "Wavenet": [
        "ja-JP-Wavenet-A", "ja-JP-Wavenet-B", "ja-JP-Wavenet-C", "ja-JP-Wavenet-D",
    ],
    "Standard": [
        "ja-JP-Standard-A", "ja-JP-Standard-B", "ja-JP-Standard-C", "ja-JP-Standard-D",
    ],
}
VOICE_FLAT = [v for voices in VOICE_OPTIONS.values() for v in voices]

# ── スクリプト入力 ──────────────────────────────
st.header("① スクリプト")
script_input = st.text_area(
    "セリフを入力（[キャラ1] / [キャラ2] 形式）",
    height=250,
    placeholder="[キャラ1] こんにちは！\n[キャラ2] 先生、今日は何を学ぶんですか？",
)

# ── キャラ画像 ──────────────────────────────────
st.header("② キャラクター画像")
col1, col2 = st.columns(2)
with col1:
    chara1_file = st.file_uploader("キャラ1（先生）", type=["png", "jpg", "jpeg"])
with col2:
    chara2_file = st.file_uploader("キャラ2（生徒）", type=["png", "jpg", "jpeg"])

# ── 背景画像 ────────────────────────────────────
st.header("③ 背景画像（任意）")
bg_file = st.file_uploader("背景画像（省略時はグラデーション）", type=["png", "jpg", "jpeg"])

# ── 声設定 & デモ ────────────────────────────────
st.header("④ 声設定・試聴")
col1, col2 = st.columns(2)
with col1:
    voice1 = st.selectbox("キャラ1（先生）の声", VOICE_FLAT,
                          index=VOICE_FLAT.index("ja-JP-Neural2-B"),
                          format_func=lambda v: next(
                              f"[{g}] {v}" for g, vs in VOICE_OPTIONS.items() if v in vs))
with col2:
    voice2 = st.selectbox("キャラ2（生徒）の声", VOICE_FLAT,
                          index=VOICE_FLAT.index("ja-JP-Neural2-D"),
                          format_func=lambda v: next(
                              f"[{g}] {v}" for g, vs in VOICE_OPTIONS.items() if v in vs))

demo_text = st.text_input("試聴テキスト", value="こんにちは！よろしくお願いします。")
dcol1, dcol2 = st.columns(2)
with dcol1:
    if st.button("🔊 キャラ1を試聴", use_container_width=True):
        with st.spinner("音声生成中..."):
            cfg = {"name": voice1, "speaking_rate": 0.95, "pitch": -2.0}
            audio = synthesize(demo_text, "chara1", voice_config=cfg)
        st.audio(audio, format="audio/wav")
with dcol2:
    if st.button("🔊 キャラ2を試聴", use_container_width=True):
        with st.spinner("音声生成中..."):
            cfg = {"name": voice2, "speaking_rate": 1.05, "pitch": 1.0}
            audio = synthesize(demo_text, "chara2", voice_config=cfg)
        st.audio(audio, format="audio/wav")

# ── 読み方リスト ────────────────────────────────
with st.expander("📖 読み方リスト（任意）"):
    st.caption("特定の単語の読み方を指定できます。タブ区切りで「元の表記 → 読み方」の形式で入力してください。")
    reading_list_input = st.text_area(
        "読み方リスト",
        height=150,
        placeholder="mMEDICCI\tエムメディチ\nPython\tパイソン",
        label_visibility="collapsed",
    )
    reading_list_file = st.file_uploader("または .txt ファイルをアップロード", type=["txt"])

# ── 生成ボタン ──────────────────────────────────
st.divider()
if st.button("🎬 動画を生成", type="primary", use_container_width=True):
    # バリデーション
    if not script_input.strip():
        st.error("スクリプトを入力してください。")
        st.stop()
    if not chara1_file or not chara2_file:
        st.error("キャラ1・キャラ2の画像を両方アップロードしてください。")
        st.stop()

    tmpfiles = []
    try:
        with st.status("動画を生成中...", expanded=True) as status:

            # スクリプトパース
            st.write("📝 スクリプトを解析中...")
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(script_input)
                script_path = f.name
            tmpfiles.append(script_path)
            lines = parse_script(script_path)
            if not lines:
                st.error("有効なセリフが見つかりませんでした。フォーマットを確認してください。")
                st.stop()
            total_lines = len(lines)
            st.write(f"  → {total_lines} 行のセリフを検出")

            # キャラ画像保存
            def save_upload(uploaded, suffix):
                ext = Path(uploaded.name).suffix or suffix
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(uploaded.read())
                tmp.close()
                tmpfiles.append(tmp.name)
                return tmp.name

            chara1_path = save_upload(chara1_file, ".png")
            chara2_path = save_upload(chara2_file, ".png")
            bg_path = save_upload(bg_file, ".png") if bg_file else None

            voice_configs = {
                "chara1": {"name": voice1, "speaking_rate": 0.95, "pitch": -2.0},
                "chara2": {"name": voice2, "speaking_rate": 1.05, "pitch": 1.0},
            }
            # 読み方リスト（UIテキスト > アップロードファイル > input/reading_list.txt の優先順）
            reading_list = {}
            if reading_list_file:
                content = reading_list_file.read().decode("utf-8")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        reading_list[parts[0]] = parts[1]
            elif reading_list_input.strip():
                for line in reading_list_input.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        reading_list[parts[0]] = parts[1]
            else:
                default_path = BASE_DIR / "input" / "reading_list.txt"
                if default_path.exists():
                    reading_list = load_reading_list(str(default_path))
            if reading_list:
                st.write(f"  → 読み方リスト: {len(reading_list)} 件")

            # 音声合成（1行ずつ進捗表示）
            st.write("🎙️ 音声を合成中...")
            progress = st.progress(0, text="0 / {} 行".format(total_lines))
            synthesized = []
            for i, line in enumerate(lines):
                chara = line["chara"]
                cfg = voice_configs.get(chara, voice_configs["chara1"])
                audio_bytes = synthesize(line["text"], chara, reading_list, cfg)
                with wave.open(io.BytesIO(audio_bytes)) as wf:
                    duration = wf.getnframes() / wf.getframerate()
                synthesized.append({"chara": chara, "text": line["text"], "audio": audio_bytes, "duration": duration})
                progress.progress((i + 1) / total_lines, text=f"{i + 1} / {total_lines} 行")

            total_dur = sum(s["duration"] for s in synthesized)
            estimated_min = int(total_dur * 6 / 60) + 1  # 経験則: 音声1秒≒6秒のレンダリング
            st.write(f"  → 合計 {total_dur:.1f} 秒の音声（動画生成 約{estimated_min}分）")

            # 動画生成
            st.write(f"🎞️ 動画を生成中... （約{estimated_min}分かかります）")
            output_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            output_tmp.close()
            tmpfiles.append(output_tmp.name)

            build_video(
                lines=synthesized,
                chara1_path=chara1_path,
                chara2_path=chara2_path,
                output_path=output_tmp.name,
                bg_path=bg_path,
            )

            status.update(label="✅ 生成完了！", state="complete")

        # ダウンロードボタン
        with open(output_tmp.name, "rb") as f:
            st.download_button(
                label="⬇️ 動画をダウンロード",
                data=f.read(),
                file_name="output.mp4",
                mime="video/mp4",
                use_container_width=True,
            )

    except Exception as e:
        st.error(f"エラーが発生しました: {e}")

    finally:
        for path in tmpfiles:
            try:
                os.unlink(path)
            except Exception:
                pass
