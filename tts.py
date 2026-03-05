"""Google Cloud TTS module."""
import io
import json
import os
import tempfile
from google.cloud import texttospeech
from google.oauth2 import service_account


def _get_client():
    """認証済みTTSクライアントを返す。Streamlit Secrets or 環境変数に対応。"""
    # Streamlit Cloud: st.secrets["gcp"] にTOML形式で格納している場合
    try:
        import streamlit as st
        if "gcp" in st.secrets:
            credentials = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp"]),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return texttospeech.TextToSpeechClient(transport="rest", credentials=credentials)
    except ImportError:
        pass  # Streamlit未インストール（CLI実行時）

    # ローカル: GOOGLE_APPLICATION_CREDENTIALS 環境変数
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and os.path.exists(creds_path):
        with open(creds_path) as f:
            creds_dict = json.load(f)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return texttospeech.TextToSpeechClient(transport="rest", credentials=credentials)

    raise RuntimeError("GCP認証情報が見つかりません。")

# デフォルト声設定
VOICE_CONFIGS = {
    "chara1": {
        "name": "ja-JP-Neural2-B",   # 男性・落ち着き（先生）
        "speaking_rate": 0.95,
        "pitch": -2.0,
    },
    "chara2": {
        "name": "ja-JP-Neural2-D",   # 女性・明るい（生徒）
        "speaking_rate": 1.05,
        "pitch": 1.0,
    },
}


def load_reading_list(path: str) -> dict[str, str]:
    """
    読み方変換リストファイルを読み込んで辞書を返す。

    フォーマット:
        元の表記<タブ>読み方   # タブ区切り
        # で始まる行はコメント、空行は無視
    """
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping


def _preprocess_for_tts(text: str, reading_list: dict[str, str] | None = None) -> str:
    """TTS用テキスト正規化（読み上げ専用。字幕表示には元テキストを使う）。"""
    if reading_list:
        for src, dst in reading_list.items():
            text = text.replace(src, dst)
    return text


def synthesize(text: str, chara: str, reading_list: dict[str, str] | None = None, voice_config: dict | None = None) -> bytes:
    """テキストをGoogle Cloud TTSで音声合成してMP3バイト列を返す。"""
    tts_text = _preprocess_for_tts(text, reading_list)
    cfg = voice_config or VOICE_CONFIGS.get(chara, VOICE_CONFIGS["chara1"])

    client = _get_client()

    synthesis_input = texttospeech.SynthesisInput(text=tts_text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ja-JP",
        name=cfg["name"],
    )
    # Chirp3-HD は speaking_rate / pitch 非対応
    if "Chirp3-HD" in cfg["name"]:
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        )
    else:
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            speaking_rate=cfg.get("speaking_rate", 1.0),
            pitch=cfg.get("pitch", 0.0),
        )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def synthesize_lines(lines: list[dict], voice_configs: dict | None = None, reading_list: dict[str, str] | None = None) -> list[dict]:
    """
    原稿行リストを受け取り、各行に音声バイト列と再生時間を付与して返す。
    並列リクエストで高速化。

    Args:
        lines: [{"chara": "chara1" | "chara2", "text": str}, ...]
        voice_configs: {"chara1": {...}, "chara2": {...}} (Noneならデフォルト使用)

    Returns:
        [{"chara": str, "text": str, "audio": bytes, "duration": float}, ...]
    """
    import wave
    from concurrent.futures import ThreadPoolExecutor, as_completed

    configs = VOICE_CONFIGS.copy()
    if voice_configs:
        configs.update(voice_configs)

    def _process(i, line):
        chara = line["chara"]
        text = line["text"]
        audio_bytes = synthesize(text, chara, reading_list, configs.get(chara))
        with wave.open(io.BytesIO(audio_bytes)) as wf:
            duration = wf.getnframes() / wf.getframerate()
        return i, {"chara": chara, "text": text, "audio": audio_bytes, "duration": duration}

    results = [None] * len(lines)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_process, i, line): i for i, line in enumerate(lines)}
        for future in as_completed(futures):
            i, item = future.result()
            results[i] = item

    return results
