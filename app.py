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
from gtts import gTTS # 🔥 新增：谷歌语音库

# ================= 1. 环境与配置管理 =================

for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

st.set_page_config(page_title="跟读助手 Pro (双引擎版)", layout="wide", page_icon="🦋")

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
        "api_key": ""
    }
    try:
        if "SILICON_KEY" in st.secrets:
            config["api_key"] = st.secrets["SILICON_KEY"]
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

# ================= 2. 功能函数 =================

def load_vocab():
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_vocab(vocab_list):
    try:
        with open(VOCAB_FILE, "w", encoding="utf-8") as f:
            json.dump(vocab_list, f, ensure_ascii=False, indent=2)
    except: pass

def compress_image(image):
    image.thumbnail((1024, 1024))
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# 声音映射表 (微软)
VOICE_MAP = {
    "🇬🇧 英语 (English)": [("en-GB-RyanNeural", "Ryan (英)"), ("en-US-ChristopherNeural", "Chris (美)")],
    "🇫🇷 法语 (Français)": [("fr-FR-HenriNeural", "Henri (法)"), ("fr-FR-DeniseNeural", "Denise (法)")],
    "🇩🇪 德语 (Deutsch)": [("de-DE-ConradNeural", "Conrad (德)"), ("de-DE-KatjaNeural", "Katja (德)")],
    "🇪🇸 西班牙语 (Español)": [("es-ES-AlvaroNeural", "Alvaro (西)"), ("es-ES-ElviraNeural", "Elvira (西)")],
    "🇷🇺 俄语 (Русский)": [("ru-RU-DmitryNeural", "Dmitry (俄)"), ("ru-RU-SvetlanaNeural", "Svetlana (俄)")],
    "🇯🇵 日语 (日本語)": [("ja-JP-KeitaNeural", "Keita (日)"), ("ja-JP-NanamiNeural", "Nanami (日)")]
}

# 谷歌语音代码映射 (备用)
GTTS_LANG_MAP = {
    "🇬🇧 英语 (English)": "en",
    "🇫🇷 法语 (Français)": "fr",
    "🇩🇪 德语 (Deutsch)": "de",
    "🇪🇸 西班牙语 (Español)": "es",
    "🇷🇺 俄语 (Русский)": "ru",
    "🇯🇵 日语 (日本語)": "ja"
}

def get_default_voice_for_lang(lang_name):
    if lang_name in VOICE_MAP: return VOICE_MAP[lang_name][0][0]
    return "en-GB-RyanNeural"

def match_language_key(detected_lang_str):
    if not detected_lang_str: return None
    s = detected_lang_str.lower()
    if "english" in s: return "🇬🇧 英语 (English)"
    if "french" in s or "français" in s: return "🇫🇷 法语 (Français)"
    if "german" in s or "deutsch" in s: return "🇩🇪 德语 (Deutsch)"
    if "spanish" in s or "español" in s: return "🇪🇸 西班牙语 (Español)"
    if "russian" in s or "русский" in s: return "🇷🇺 俄语 (Русский)"
    if "japanese" in s or "日本" in s: return "🇯🇵 日语 (日本語)"
    return None

async def create_anki_package(selected_items):
    deck_id = random.randrange(1 << 30, 1 << 31)
    deck = genanki.Deck(deck_id, '跟读助手生词本')
    model_id = random.randrange(1 << 30, 1 << 31)
    my_model = genanki.Model(
        model_id, 'Simple Model with Audio',
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{'name': 'Card 1', 'qfmt': '{{Question}}<br>{{Audio}}', 'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}'}])

    media_files = []
    progress_bar = st.progress(0)
    
    for idx, item in enumerate(selected_items):
        lang = item.get('lang', '🇬🇧 英语 (English)')
        voice = get_default_voice_for_lang(lang)
        audio_filename = f"audio_{random.randint(1000,9999)}_{idx}.mp3"
        try:
            # Anki 打包时也尝试双引擎
            communicate = edge_tts.Communicate(item['word'], voice)
            await communicate.save(audio_filename)
        except:
            try:
                # 备用谷歌
                g_lang = GTTS_LANG_MAP.get(lang, "en")
                tts = gTTS(text=item['word'], lang=g_lang)
                tts.save(audio_filename)
            except: pass # 如果都失败则跳过

        if os.path.exists(audio_filename):
            media_files.append(audio_filename)
            note = genanki.Note(
                model=my_model,
                fields=[
                    f"{item['word']} <br> <small style='color:grey'>{item.get('ipa','')}</small>",
                    f"🇨🇳 {item.get('zh','')} <br> 🇷🇺 {item.get('ru','')}",
                    f"[sound:{audio_filename}]"
                ])
            deck.add_note(note)
        progress_bar.progress((idx + 1) / len(selected_items))

    output_package = genanki.Package(deck)
    output_package.media_files = media_files
    pkg_bytes = io.BytesIO()
    temp_pkg_name = "temp_output.apkg"
    output_package.write_to_file(temp_pkg_name)
    with open(temp_pkg_name, "rb") as f: final_bytes = f.read()
    os.remove(temp_pkg_name)
    for mp3 in media_files:
        if os.path.exists(mp3): os.remove(mp3)
    progress_bar.empty()
    return final_bytes

# 🔥🔥🔥 核心修改：双引擎音频生成 🔥🔥🔥
async def get_audio_bytes_memory(text, voice, rate_str, lang_choice):
    # 1. 优先尝试微软 Edge TTS (高质量)
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        mp3_fp = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_fp.write(chunk["data"])
        return mp3_fp.getvalue(), None
    except Exception as e_edge:
        # 2. 如果失败，自动降级到 Google TTS (高可用)
        print(f"EdgeTTS Failed ({e_edge}), switching to Google TTS...")
        try:
            g_lang = GTTS_LANG_MAP.get(lang_choice, "en")
            # Google 不支持调整语速，只能按默认速度
            tts = gTTS(text=text, lang=g_lang)
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), f"注意：微软语音服务繁忙，已自动切换至 Google 引擎 (暂不支持倍速)。"
        except Exception as e_google:
            return None, f"所有语音引擎均失败: {e_edge} | {e_google}"

def silicon_ocr_multilang(image, api_key, model_id):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
    base64_image = compress_image(image)
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": [{"type": "text", "text": "Extract all legible text. Keep original language."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]
        )
        return response.choices[0].message.content, None
    except Exception as e: return None, str(e)

def silicon_vocab_lookup_multilang(word, api_key, model_id):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
    prompt = f"""
    You are a strictly formatted dictionary API. User input: "{word}".
    Task: 1. Detect language. 2. Provide IPA if English. 3. Translate to Chinese (zh) and Russian (ru). 
    4. Keep definitions concise. Return ONLY JSON: {{ "detected_lang": "...", "ipa": "...", "zh": "...", "ru": "..." }}
    """
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content), None
    except Exception as e: return None, str(e)

def silicon_translate_text(text, api_key, model_id, system_prompt):
    client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
    full_prompt = f"{system_prompt}\n\n[Content to Translate]:\n{text}"
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": full_prompt}]
        )
        return response.choices[0].message.content, None
    except Exception as e: return None, str(e)

# ================= 5. 界面 UI =================

st.title("🦋 跟读助手 Pro (Cloud Stable)")

if 'vocab_book' not in st.session_state: st.session_state.vocab_book = load_vocab()
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'audio_cache' not in st.session_state: st.session_state.audio_cache = None
if 'translation_result' not in st.session_state: st.session_state.translation_result = ""
if 'temp_word_audio' not in st.session_state: st.session_state.temp_word_audio = {}

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 设置")
    local_ip = get_local_ip()
    if local_ip != "127.0.0.1": st.caption(f"🏠 局域网地址: http://{local_ip}:8501")

    default_key_val = st.session_state.app_config.get("api_key", "")
    api_input = st.text_input("SiliconFlow Key", value=default_key_val, type="password")

    if api_input != st.session_state.app_config.get("api_key"):
        st.session_state.app_config["api_key"] = api_input
        save_config(st.session_state.app_config)

    with st.expander("🤖 模型配置", expanded=False):
        chat_model_input = st.text_input("模型", value=st.session_state.app_config.get("chat_model", "deepseek-ai/DeepSeek-V3"))
        ocr_model_input = st.text_input("OCR", value=st.session_state.app_config.get("ocr_model", "Qwen/Qwen2.5-VL-72B-Instruct"))
        trans_prompt_input = st.text_area("翻译提示词", value=st.session_state.app_config.get("trans_prompt", ""), height=80)
        
        for k, v in [("chat_model", chat_model_input), ("ocr_model", ocr_model_input), ("trans_prompt", trans_prompt_input)]:
            if v != st.session_state.app_config.get(k):
                st.session_state.app_config[k] = v; save_config(st.session_state.app_config)

    st.divider()
    lang_choice = st.selectbox("🌍 语言", list(VOICE_MAP.keys()), index=0)
    available_voices = VOICE_MAP[lang_choice]
    voice_id = st.radio("🎙️ 声音", [v[0] for v in available_voices], format_func=lambda x: next(v[1] for v in available_voices if v[0] == x))
    speed_int = st.slider("🐇 语速", -50, 50, 0, 5); rate_str = f"{speed_int:+d}%"

    if not api_input:
        st.warning("⚠️ 请输入 API Key 才能开始使用")
        st.stop()

# --- 主界面 ---
col1, col2 = st.columns([1.6, 1.4])

with col1:
    st.subheader(f"1. 学习内容")
    tab_ocr, tab_txt = st.tabs(["📷 拍照识别", "✍️ 手动输入"])
    with tab_ocr:
        uploaded = st.file_uploader("上传图片", type=['jpg', 'png'])
        if uploaded and st.button("开始识别 (OCR)"):
            with st.spinner("识别中..."):
                img = Image.open(uploaded)
                res, err = silicon_ocr_multilang(img, api_input, ocr_model_input)
                if res: 
                    st.session_state.current_text = res; st.session_state.translation_result = ""; st.rerun()
                else: st.error(f"失败: {err}")
    with tab_txt:
        txt = st.text_area("输入文本", height=100)
        if st.button("确认文本"): 
            st.session_state.current_text = txt; st.session_state.translation_result = ""; st.rerun()

    if st.session_state.current_text:
        st.markdown("---")
        final_text = st.text_area("📝 正文内容", value=st.session_state.current_text, height=200)
        
        c_tts, c_trans = st.columns([1, 1])
        with c_tts:
            if st.button(f"▶️ 播放语音 ({rate_str})", type="primary", use_container_width=True):
                with st.spinner("合成语音中..."):
                    # 🔥 传入 lang_choice 以便备用引擎使用
                    audio_bytes, msg = asyncio.run(get_audio_bytes_memory(final_text, voice_id, rate_str, lang_choice))
                    
                    if audio_bytes:
                        st.session_state.audio_cache = audio_bytes
                        if msg: st.toast(msg, icon="⚠️") # 提示用户切换了引擎
                        st.rerun() 
                    else:
                        st.error(f"语音合成失败: {msg}")
        
        if st.session_state.audio_cache:
            st.audio(st.session_state.audio_cache, format='audio/mpeg')

        with st.expander("🇨🇳 全文翻译 (DeepSeek)", expanded=False):
            if st.button("🚀 开始翻译"):
                with st.spinner("DeepSeek 思考中..."):
                    trans_res, trans_err = silicon_translate_text(final_text, api_input, chat_model_input, trans_prompt_input)
                    if trans_res: st.session_state.translation_result = trans_res
                    else: st.error(f"翻译失败: {trans_err}")
            
            if st.session_state.translation_result:
                st.info(st.session_state.translation_result)

with col2:
    st.subheader("📚 智能单词本")
    with st.form("lookup", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        wq = c1.text_input("查词", label_visibility="collapsed", placeholder="输入单词 (自动识别语言)...")
        if c2.form_submit_button("🔍"):
            if wq.strip():
                with st.spinner("查询中..."):
                    info, err = silicon_vocab_lookup_multilang(wq, api_input, chat_model_input)
                    if info:
                        detected_lang = info.get("detected_lang", "")
                        matched_key = match_language_key(detected_lang)
                        final_lang = matched_key if matched_key else lang_choice
                        
                        st.session_state.vocab_book.insert(0, {
                            "word": wq, "lang": final_lang, "date": datetime.now().strftime("%Y-%m-%d"),
                            "ipa": info.get("ipa", ""), "zh": info.get("zh", ""), "ru": info.get("ru", "")
                        })
                        save_vocab(st.session_state.vocab_book)
                        if matched_key and matched_key != lang_choice:
                            st.toast(f"已自动归类至: {matched_key.split(' ')[1]}", icon="🔀")
                        else: st.toast("已保存", icon="✅")
                        st.rerun()
                    else: st.error(f"API错误: {err}")

    st.divider()
    
    filtered_vocab = [v for v in st.session_state.vocab_book if v.get('lang', '🇬🇧 英语 (English)') == lang_choice]
    
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
                        # 🔥 单词播放也使用双引擎
                        adata, _ = asyncio.run(get_audio_bytes_memory(item['word'], voice_id, "+0%", lang_choice))
                        if adata: st.session_state.temp_word_audio[item['word']] = adata; st.rerun()
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
                if st.button("📤 导出Anki包"):
                    with st.spinner("打包中..."):
                        apkg_bytes = asyncio.run(create_anki_package(checked_items))
                        st.download_button("⬇️ 下载 .apkg", data=apkg_bytes, file_name=f"anki_{datetime.now().strftime('%m%d')}.apkg")
            with col_del:
                if st.button("🗑️ 删除选中"):
                    rem_words = [i['word'] for i in checked_items]
                    st.session_state.vocab_book = [i for i in st.session_state.vocab_book if i['word'] not in rem_words]
                    save_vocab(st.session_state.vocab_book)
                    st.rerun()
    else:
        st.caption(f"暂无 {lang_choice} 生词")