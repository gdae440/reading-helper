import streamlit as st
from openai import OpenAI
import edge_tts
import asyncio
import json
import os
import io
import base64
import random
from datetime import datetime
from PIL import Image
import genanki
import socket
from gtts import gTTS

# ================= 1. 环境与配置 =================

for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

st.set_page_config(page_title="跟读助手 Pro (V10.1 Ollie版)", layout="wide", page_icon="🦋")

VOCAB_FILE = "my_vocab.json"
CONFIG_FILE = "config.json"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "127.0.0.1"

def load_config():
    config = {
        "chat_model": "deepseek-ai/DeepSeek-V3",
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "trans_prompt": "Translate the following text into fluent, natural Chinese.",
        "api_key": "",
        "sf_tts_model_id": "FunAudioLLM/CosyVoice2-0.5B" 
    }
    try:
        if "SILICON_KEY" in st.secrets: config["api_key"] = st.secrets["SILICON_KEY"]
    except: pass
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except: pass
    return config

def save_config(config_dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
    except: pass

if 'app_config' not in st.session_state:
    st.session_state.app_config = load_config()

# ================= 2. 核心数据 (音色库) =================

# 1. Edge 本地音色 (免费/高质量)
# 注意：Ollie 是 Azure 付费音色，Edge 接口不一定开放，标为“尝试”
VOICE_MAP_EDGE = {
    "🇬🇧 英语": [
        ("en-GB-RyanNeural", "Ryan (标准英音/男)"), 
        ("en-GB-SoniaNeural", "Sonia (标准英音/女)"),
        ("en-GB-OllieNeural", "Ollie (磁性英音/男-尝试)"), # 🔥 你想要的 Ollie
        ("en-US-ChristopherNeural", "Chris (美音/男)"),
        ("en-US-AriaNeural", "Aria (美音/女)")
    ],
    "🇫🇷 法语": [("fr-FR-HenriNeural", "Henri (法/男)"), ("fr-FR-DeniseNeural", "Denise (法/女)")],
    "🇩🇪 德语": [("de-DE-ConradNeural", "Conrad (德/男)"), ("de-DE-KatjaNeural", "Katja (德/女)")],
    "🇷🇺 俄语": [("ru-RU-DmitryNeural", "Dmitry (俄/男)"), ("ru-RU-SvetlanaNeural", "Svetlana (俄/女)")],
}

# 2. SiliconFlow 音色 (CosyVoice2)
VOICE_MAP_SF = {
    "默认女声 (Alex)": "alex",
    "默认男声 (Bob)": "bob", 
    "新闻主播 (Anna)": "anna",
    "英伦男声 (Benjamin)": "benjamin", # 🔥 类似 Ollie 的风格
    "深沉男声 (Charles)": "charles",
    "OpenAI风格-女 (Nova)": "nova",
    "OpenAI风格-男 (Echo)": "echo"
}

GTTS_LANG_MAP = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru"}

def load_vocab():
    if os.path.exists(VOCAB_FILE):
        try: return json.load(open(VOCAB_FILE, "r", encoding="utf-8"))
        except: return []
    return []

def save_vocab(vocab_list):
    try: json.dump(vocab_list, open(VOCAB_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except: pass

def compress_image(image):
    image.thumbnail((1024, 1024)); buffered = io.BytesIO(); image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# ================= 3. 音频处理核心 =================

async def get_audio_bytes_mixed(text, engine_type, voice_id, rate_str, lang_choice, app_config):
    
    # 1. Edge
    if engine_type == "Edge (本地推荐)":
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge ({voice_id}) 失败: {e} (Ollie可能未开放，请换Ryan)"

    # 2. SiliconFlow (付费)
    elif engine_type == "SiliconFlow (云端/付费)":
        api_key = app_config["api_key"]
        if not api_key: return None, "请先输入 API Key"
        client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
        try:
            response = client.audio.speech.create(
                model="FunAudioLLM/CosyVoice2-0.5B",
                voice=voice_id,
                input=text,
                speed=1.0 
            )
            return response.content, None
        except Exception as e: return None, f"SF TTS 失败: {e}"

    # 3. Google
    elif engine_type == "Google (云端保底)":
        try:
            g_lang = GTTS_LANG_MAP.get(lang_choice, "en")
            tts = gTTS(text=text, lang=g_lang)
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Google 失败: {e}"

    return None, "未知引擎"

async def create_anki_package(selected_items):
    deck_id = random.randrange(1 << 30, 1 << 31)
    deck = genanki.Deck(deck_id, '跟读助手')
    my_model = genanki.Model(random.randrange(1<<30, 1<<31), 'Model', fields=[{'name':'Q'},{'name':'A'},{'name':'Audio'}], templates=[{'name':'C1','qfmt':'{{Q}}<br>{{Audio}}','afmt':'{{FrontSide}}<hr>{{A}}'}])
    media_files = []; progress = st.progress(0)
    for idx, item in enumerate(selected_items):
        try:
            fname = f"audio_{idx}_{random.randint(100,999)}.mp3"
            tts = gTTS(text=item['word'], lang='en'); tts.save(fname) 
            media_files.append(fname)
            deck.add_note(genanki.Note(model=my_model, fields=[item['word'], item.get('zh',''), f"[sound:{fname}]"]))
        except: pass
        progress.progress((idx+1)/len(selected_items))
    pkg = genanki.Package(deck); pkg.media_files = media_files
    out = io.BytesIO(); pkg.write_to_file(out)
    for f in media_files: os.remove(f)
    progress.empty(); return out.getvalue()

# ================= 4. API 查词与翻译 =================
def silicon_ocr_multilang(image, api_key, model_id):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1"); base64_image = compress_image(image)
    try: response = client.chat.completions.create(model=model_id, messages=[{"role": "user", "content": [{"type": "text", "text": "Extract all legible text. Keep original language."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]); return response.choices[0].message.content, None
    except Exception as e: return None, str(e)
def silicon_vocab_lookup_multilang(word, api_key, model_id):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
    prompt = f"""Dictionary API. User input: "{word}". Return JSON: {{ "detected_lang": "...", "ipa": "...", "zh": "...", "ru": "..." }} (Concise)"""
    try: response = client.chat.completions.create(model=model_id, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}); return json.loads(response.choices[0].message.content), None
    except Exception as e: return None, str(e)
def silicon_translate_text(text, api_key, model_id, system_prompt):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1"); full_prompt = f"{system_prompt}\n\n{text}"
    try: response = client.chat.completions.create(model=model_id, messages=[{"role": "user", "content": full_prompt}]); return response.choices[0].message.content, None
    except Exception as e: return None, str(e)

# ================= 5. 界面 UI =================

st.title("🦋 跟读助手 Pro (V10.1 Ollie版)")

if 'vocab_book' not in st.session_state: st.session_state.vocab_book = load_vocab()
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'audio_cache' not in st.session_state: st.session_state.audio_cache = None
if 'translation_result' not in st.session_state: st.session_state.translation_result = ""
if 'temp_word_audio' not in st.session_state: st.session_state.temp_word_audio = {}

with st.sidebar:
    st.header("⚙️ 设置")
    local_ip = get_local_ip()
    if local_ip != "127.0.0.1": st.caption(f"🏠 局域网: http://{local_ip}:8501")

    # Key 配置
    default_key = st.session_state.app_config.get("api_key", "")
    api_input = st.text_input("SiliconFlow Key", value=default_key, type="password")
    if api_input != st.session_state.app_config.get("api_key"):
        st.session_state.app_config["api_key"] = api_input; save_config(st.session_state.app_config)

    st.divider()
    tts_engine = st.radio("🔊 语音引擎", ["Edge (本地推荐)", "SiliconFlow (云端/付费)", "Google (云端保底)"], index=0)
    
    voice_id = "default"
    
    if tts_engine == "SiliconFlow (云端/付费)":
        st.info("💎 使用 CosyVoice2")
        voice_choice = st.selectbox("🎙️ 选择音色", list(VOICE_MAP_SF.keys()))
        voice_id = VOICE_MAP_SF[voice_choice]
        
    elif tts_engine == "Edge (本地推荐)":
        lang_choice_temp = st.selectbox("🌍 语言预览", list(VOICE_MAP_EDGE.keys()), index=0, key="edge_lang_prev")
        available_voices = VOICE_MAP_EDGE[lang_choice_temp]
        voice_id = st.radio("🎙️ 音色", [v[0] for v in available_voices], format_func=lambda x: next(v[1] for v in available_voices if v[0] == x))

    st.divider()
    lang_choice = st.selectbox("🌍 学习语言", list(VOICE_MAP_EDGE.keys()), index=0)
    speed_int = st.slider("🐇 语速", -50, 50, 0, 5); rate_str = f"{speed_int:+d}%"
    
    if not api_input: st.warning("⚠️ 请输入 Key"); st.stop()

# --- 主界面 ---
col1, col2 = st.columns([1.6, 1.4])

with col1:
    st.subheader("1. 学习内容")
    tab_ocr, tab_txt = st.tabs(["📷 拍照识别", "✍️ 手动输入"])
    with tab_ocr:
        uploaded = st.file_uploader("上传图片", type=['jpg', 'png'])
        if uploaded and st.button("开始识别"):
            img = Image.open(uploaded)
            res, _ = silicon_ocr_multilang(img, api_input, "Qwen/Qwen2.5-VL-72B-Instruct")
            if res: st.session_state.current_text = res; st.session_state.translation_result = ""; st.rerun()
    with tab_txt:
        txt = st.text_area("输入文本", height=100)
        if st.button("确认"): st.session_state.current_text = txt; st.rerun()

    if st.session_state.current_text:
        st.markdown("---")
        final_text = st.text_area("正文", value=st.session_state.current_text, height=200)
        
        # 播放
        if st.button(f"▶️ 播放 ({tts_engine})", type="primary", use_container_width=True):
            with st.spinner(f"正在生成..."):
                ab, err = asyncio.run(get_audio_bytes_mixed(
                    final_text, tts_engine, voice_id, rate_str, lang_choice, st.session_state.app_config
                ))
                if ab: st.session_state.audio_cache = ab; st.rerun()
                else: st.error(err)
        
        if st.session_state.audio_cache:
            st.audio(st.session_state.audio_cache, format='audio/mpeg')

        # 翻译
        with st.expander("🇨🇳 全文翻译", expanded=False):
            if st.button("🚀 翻译"):
                res, _ = silicon_translate_text(final_text, api_input, "deepseek-ai/DeepSeek-V3", "Translate to Chinese.")
                if res: st.info(res)

with col2:
    st.subheader("📚 智能单词本")
    with st.form("lookup"):
        c1, c2 = st.columns([3,1])
        wq = c1.text_input("查词", label_visibility="collapsed")
        if c2.form_submit_button("🔍"):
            info, _ = silicon_vocab_lookup_multilang(wq, api_input, "deepseek-ai/DeepSeek-V3")
            if info: 
                st.session_state.vocab_book.insert(0, {"word": wq, "lang": lang_choice, "date": "Today", **info})
                save_vocab(st.session_state.vocab_book)
                st.rerun()

    st.divider()
    for item in st.session_state.vocab_book[:5]:
        c1, c2 = st.columns([0.8, 0.2])
        c1.markdown(f"**{item['word']}** {item.get('ipa','')}\n\n{item.get('zh','')}")
        if c2.button("🔊", key=f"p_{item['word']}"):
            ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], tts_engine, voice_id, "+0%", lang_choice, st.session_state.app_config))
            if ab: st.session_state.temp_word_audio[item['word']] = ab; st.rerun()
        if item['word'] in st.session_state.temp_word_audio:
            st.audio(st.session_state.temp_word_audio[item['word']], autoplay=True)
            del st.session_state.temp_word_audio[item['word']]