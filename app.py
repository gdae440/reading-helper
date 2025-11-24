import streamlit as st
from openai import OpenAI
import edge_tts
from gtts import gTTS
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

# ================= 1. 环境与配置 =================

# 针对本地/国际版，清理可能干扰的代理设置，或者根据您本地网络情况自行调整
# 如果您本地开了全局代理，通常不需要额外设置
for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

st.set_page_config(page_title="跟读助手 Pro (V11.1 国际版)", layout="wide", page_icon="🦋")

VOCAB_FILE = "my_vocab.json"

def load_config():
    config = {
        "chat_model": "deepseek-ai/DeepSeek-V3",
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "trans_prompt": "Translate the following text into fluent, natural Chinese.",
        "api_key": "",
        "sf_tts_model_id": "FunAudioLLM/CosyVoice2-0.5B" 
    }
    env_key = os.getenv("SILICON_KEY")
    if env_key: config["api_key"] = env_key
    try:
        if "SILICON_KEY" in st.secrets: config["api_key"] = st.secrets["SILICON_KEY"]
    except: pass
    return config

if 'app_config' not in st.session_state:
    st.session_state.app_config = load_config()

# ================= 2. 核心数据 =================

VOICE_MAP_EDGE = {
    "🇬🇧 英语": [("en-GB-RyanNeural", "Ryan (英/男)"), ("en-US-ChristopherNeural", "Chris (美/男)"), ("en-US-AriaNeural", "Aria (美/女)")],
    "🇫🇷 法语": [("fr-FR-HenriNeural", "Henri (法/男)"), ("fr-FR-DeniseNeural", "Denise (法/女)")],
    "🇩🇪 德语": [("de-DE-ConradNeural", "Conrad (德/男)"), ("de-DE-KatjaNeural", "Katja (德/女)")],
    "🇷🇺 俄语": [("ru-RU-DmitryNeural", "Dmitry (俄/男)"), ("ru-RU-SvetlanaNeural", "Svetlana (俄/女)")],
}

VOICE_MAP_SF = {
    "男声 - Benjamin (英伦风)": "FunAudioLLM/CosyVoice2-0.5B:benjamin", 
    "男声 - Alex (沉稳)": "FunAudioLLM/CosyVoice2-0.5B:alex",
    "男声 - Bob (欢快)": "FunAudioLLM/CosyVoice2-0.5B:bob",
    "女声 - Anna (新闻)": "FunAudioLLM/CosyVoice2-0.5B:anna",
    "女声 - Bella (温柔)": "FunAudioLLM/CosyVoice2-0.5B:bella",
    "女声 - Claire (清晰)": "FunAudioLLM/CosyVoice2-0.5B:claire"
}

# Google 语言代码映射
LANG_MAP_GOOGLE = {
    "🇬🇧 英语": "en",
    "🇫🇷 法语": "fr",
    "🇩🇪 德语": "de",
    "🇷🇺 俄语": "ru"
}

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

# ================= 3. 音频处理核心 (Edge / SiliconFlow / Google) =================

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, app_config):
    """
    engine_type: "Edge", "SiliconFlow", "Google"
    voice_id: Edge的ID, 或 SF的ID, 或 Google的语言代码(如 'en')
    """
    
    # 1. Edge TTS
    if "Edge" in engine_type:
        rate_str = f"{speed_int:+d}%"
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge 失败: {e}"

    # 2. SiliconFlow (CosyVoice)
    elif "SiliconFlow" in engine_type:
        api_key = app_config["api_key"]
        if not api_key: return None, "请先输入 API Key"
        client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
        
        model_id = "FunAudioLLM/CosyVoice2-0.5B"
        if ":" in voice_id: model_id = voice_id.split(":")[0]

        speed_float = 1.0 + (speed_int / 100.0) # 映射 -50~50 到 0.5~1.5

        try:
            response = client.audio.speech.create(
                model=model_id,
                voice=voice_id,
                input=text,
                speed=speed_float 
            )
            return response.content, None
        except Exception as e: 
            return None, f"SF TTS 失败: {e}"

    # 3. Google TTS
    elif "Google" in engine_type:
        try:
            # Google 不支持变速，speed_int 被忽略
            # voice_id 在这里实际传入的是语言代码 (如 'en')
            tts = gTTS(text=text, lang=voice_id)
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e:
            return None, f"Google TTS 失败: {e}"

    return None, "未知引擎"

# ================= 4. Anki 导出 =================

async def create_anki_package(selected_items, engine_type, voice_id, speed_int, app_config):
    deck_id = random.randrange(1 << 30, 1 << 31)
    deck = genanki.Deck(deck_id, '跟读助手生词本')
    
    my_model = genanki.Model(
        random.randrange(1 << 30, 1 << 31),
        'Simple Model with Audio',
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{'name': 'Card 1', 'qfmt': '{{Question}}<br>{{Audio}}', 'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}'}])

    media_files = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, item in enumerate(selected_items):
        status_text.text(f"生成音频 ({engine_type}): {item['word']}...")
        
        # 如果是 Google 模式，这里传入的 voice_id 应该是语言代码，需确保 UI 逻辑正确传递
        # 下方 UI 部分会处理好这个传参
        audio_data, _ = await get_audio_bytes_mixed(
            item['word'], engine_type, voice_id, speed_int, app_config
        )
        
        audio_filename = ""
        if audio_data:
            audio_filename = f"anki_{random.randint(1000,9999)}_{idx}.mp3"
            with open(audio_filename, "wb") as f:
                f.write(audio_data)
            media_files.append(audio_filename)
        
        word_field = f"{item['word']} <br> <span style='color:grey; font-size: 0.8em;'>{item.get('ipa', '')}</span>"
        meaning_field = f"🇨🇳 {item.get('zh', '')} <br> 🇷🇺 {item.get('ru', '')}"
        audio_field = f"[sound:{audio_filename}]" if audio_filename else ""

        deck.add_note(genanki.Note(model=my_model, fields=[word_field, meaning_field, audio_field]))
        progress_bar.progress((idx + 1) / len(selected_items))

    status_text.text("打包 .apkg...")
    output_package = genanki.Package(deck)
    output_package.media_files = media_files
    
    pkg_bytes = io.BytesIO()
    temp_pkg_name = "temp_anki_output.apkg"
    output_package.write_to_file(temp_pkg_name)
    
    with open(temp_pkg_name, "rb") as f: final_bytes = f.read()
    
    os.remove(temp_pkg_name)
    for f in media_files:
        if os.path.exists(f): os.remove(f)
        
    progress_bar.empty(); status_text.empty()
    return final_bytes

# ================= 5. API 查词与翻译 =================
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

# ================= 6. 界面 UI =================

st.title("🦋 跟读助手 Pro (国际版)")

if 'vocab_book' not in st.session_state: st.session_state.vocab_book = load_vocab()
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'audio_cache' not in st.session_state: st.session_state.audio_cache = None
if 'translation_result' not in st.session_state: st.session_state.translation_result = ""
if 'temp_word_audio' not in st.session_state: st.session_state.temp_word_audio = {}

with st.sidebar:
    st.header("⚙️ 设置")
    
    default_key = st.session_state.app_config.get("api_key", "")
    api_input = st.text_input("SiliconFlow Key", value=default_key, type="password")
    if api_input != st.session_state.app_config.get("api_key"):
        st.session_state.app_config["api_key"] = api_input

    st.divider()
    # 恢复 Google 选项
    tts_engine = st.radio("🔊 语音引擎", ["Edge (推荐)", "SiliconFlow (高拟真)", "Google (标准)"], index=0)
    
    voice_id = "default"
    
    # 1. SiliconFlow 设置
    if "SiliconFlow" in tts_engine:
        voice_choice = st.selectbox("🎙️ 选择音色", list(VOICE_MAP_SF.keys()))
        voice_id = VOICE_MAP_SF[voice_choice]
        
    # 2. Edge 设置
    elif "Edge" in tts_engine:
        lang_choice_temp = st.selectbox("🌍 语言预览", list(VOICE_MAP_EDGE.keys()), index=0, key="edge_lang_prev")
        available_voices = VOICE_MAP_EDGE[lang_choice_temp]
        voice_id = st.radio("🎙️ 音色", [v[0] for v in available_voices], format_func=lambda x: next(v[1] for v in available_voices if v[0] == x))

    # 3. Google 设置
    elif "Google" in tts_engine:
        st.info("ℹ️ Google TTS 仅支持标准语速。")
        # 直接使用下方的 "lang_choice" 来决定 Google 的语言
        # 这里仅做占位，实际逻辑在下面获取
        pass

    st.divider()
    lang_choice = st.selectbox("🌍 学习语言", list(VOICE_MAP_EDGE.keys()), index=0)
    
    # 如果选了 Google，直接把 voice_id 赋值为语言代码
    if "Google" in tts_engine:
        voice_id = LANG_MAP_GOOGLE.get(lang_choice, "en")

    speed_int = st.slider("🐇 语速调节", -50, 50, 0, 5, help="Edge: % | SF: 0.5x-1.5x | Google: 不支持")
    
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
        
        if st.button(f"▶️ 播放语音", type="primary", use_container_width=True):
            with st.spinner(f"正在生成..."):
                ab, err = asyncio.run(get_audio_bytes_mixed(
                    final_text, tts_engine, voice_id, speed_int, st.session_state.app_config
                ))
                if ab: st.session_state.audio_cache = ab; st.rerun()
                else: st.error(err)
        
        if st.session_state.audio_cache:
            st.audio(st.session_state.audio_cache, format='audio/mpeg')

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
                st.session_state.vocab_book.insert(0, {"word": wq, "lang": lang_choice, "date": datetime.now().strftime("%Y-%m-%d"), **info})
                save_vocab(st.session_state.vocab_book)
                st.rerun()

    st.divider()
    
    filtered_vocab = [v for v in st.session_state.vocab_book if v.get('lang', '🇬🇧 英语') == lang_choice]
    
    if filtered_vocab:
        checked_items = []
        grouped = {}
        for item in filtered_vocab:
            d = item.get('date', 'Unknown')
            if d not in grouped: grouped[d] = []
            grouped[d].append(item)
            
        for d, items in grouped.items():
            st.caption(f"📅 {d}")
            for idx, item in enumerate(items):
                c_chk, c_wd, c_ph = st.columns([0.1, 0.4, 0.5])
                with c_chk:
                    unique_key = f"chk_{item['word']}_{d}_{idx}" 
                    if st.checkbox("", key=unique_key): checked_items.append(item)
                with c_wd:
                    st.markdown(f"**{item['word']}**")
                    if item.get('ipa'): st.caption(f"[{item['ipa']}]")
                    if st.button("🔊", key=f"p_{item['word']}_{d}_{idx}"):
                        ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], tts_engine, voice_id, speed_int, st.session_state.app_config))
                        if ab: st.session_state.temp_word_audio[item['word']] = ab; st.rerun()
                with c_ph:
                    st.markdown(f"🇨🇳 {item.get('zh','')}")
                    st.markdown(f"🇷🇺 {item.get('ru','')}")
                
                if item['word'] in st.session_state.temp_word_audio:
                    st.audio(st.session_state.temp_word_audio[item['word']], format="audio/mpeg", autoplay=True)
                    del st.session_state.temp_word_audio[item['word']]
            st.divider()

        if checked_items:
            st.info(f"选中 {len(checked_items)} 个单词")
            col_exp, col_del = st.columns(2)
            with col_exp:
                # 提示当前使用的引擎，避免用户打包错了
                btn_label = f"📤 导出Anki ({tts_engine.split(' ')[0]})"
                if st.button(btn_label):
                    with st.spinner("正在生成Anki包 (包含音频)..."):
                        apkg_bytes = asyncio.run(create_anki_package(
                            checked_items, tts_engine, voice_id, speed_int, st.session_state.app_config
                        ))
                        st.download_button("⬇️ 下载 .apkg", data=apkg_bytes, file_name=f"anki_{datetime.now().strftime('%m%d')}.apkg")
            with col_del:
                if st.button("🗑️ 删除选中"):
                    rem_words = [i['word'] for i in checked_items]
                    st.session_state.vocab_book = [i for i in st.session_state.vocab_book if i['word'] not in rem_words]
                    save_vocab(st.session_state.vocab_book)
                    st.rerun()
    else:
        st.caption(f"暂无 {lang_choice} 生词")
