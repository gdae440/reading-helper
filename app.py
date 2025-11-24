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

# ================= 1. 环境与配置 =================

for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

st.set_page_config(page_title="跟读助手 Pro (V11.0 修复版)", layout="wide", page_icon="🦋")

VOCAB_FILE = "my_vocab.json"
# 移除本地 config 读写，确保云端安全
# CONFIG_FILE = "config.json"

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
    # 仅从 Secrets 读取
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

# ================= 3. 音频处理核心 (修复语速) =================

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, app_config):
    """
    speed_int: -50 到 50 的整数
    """
    
    # 1. Edge TTS (使用百分比语速)
    if "Edge" in engine_type:
        rate_str = f"{speed_int:+d}%" # 例如 "+10%"
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge ({voice_id}) 失败: {e}"

    # 2. SiliconFlow (使用浮点数语速)
    elif "SiliconFlow" in engine_type:
        api_key = app_config["api_key"]
        if not api_key: return None, "请先输入 API Key"
        client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
        
        # 解析模型
        model_id = "FunAudioLLM/CosyVoice2-0.5B"
        if ":" in voice_id: model_id = voice_id.split(":")[0]

        # 🔥 修复语速: 将 -50~50 映射为 0.5~1.5
        # 0 -> 1.0 (原速)
        # 50 -> 1.5 (1.5倍速)
        # -50 -> 0.5 (0.5倍速)
        speed_float = 1.0 + (speed_int / 100.0)

        try:
            response = client.audio.speech.create(
                model=model_id,
                voice=voice_id,
                input=text,
                speed=speed_float # 传入计算后的浮点数
            )
            return response.content, None
        except Exception as e: 
            return None, f"SF TTS 失败: {e}"

    return None, "未知引擎"

# ================= 4. Anki 导出 (修复内容缺失 & 引擎同步) =================

async def create_anki_package(selected_items, engine_type, voice_id, speed_int, app_config):
    """
    完全修复的 Anki 打包函数
    1. 传入当前引擎设置，确保生成的音频和听的一样。
    2. 修复字段映射，包含 IPA 和 俄语。
    """
    deck_id = random.randrange(1 << 30, 1 << 31)
    deck = genanki.Deck(deck_id, '跟读助手生词本')
    
    # 修复 Model 字段：增加 IPA 和 RU
    my_model = genanki.Model(
        random.randrange(1 << 30, 1 << 31),
        'Simple Model with Audio',
        fields=[
            {'name': 'Question'}, 
            {'name': 'Answer'}, 
            {'name': 'Audio'}
        ],
        templates=[
            {
                'name': 'Card 1',
                'qfmt': '{{Question}}<br>{{Audio}}', # 正面：单词+音标+发音
                'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}', # 背面：释义
            }
        ])

    media_files = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, item in enumerate(selected_items):
        status_text.text(f"正在生成音频: {item['word']}...")
        
        # 1. 生成音频 (复用核心函数，确保引擎一致)
        audio_data, _ = await get_audio_bytes_mixed(
            item['word'], engine_type, voice_id, speed_int, app_config
        )
        
        audio_filename = ""
        if audio_data:
            audio_filename = f"anki_audio_{random.randint(1000,9999)}_{idx}.mp3"
            # 写入本地临时文件给 genanki 读取
            with open(audio_filename, "wb") as f:
                f.write(audio_data)
            media_files.append(audio_filename)
        
        # 2. 准备内容 (修复内容缺失)
        # 正面：单词 + 音标 (灰色小字)
        word_field = f"{item['word']} <br> <span style='color:grey; font-size: 0.8em;'>{item.get('ipa', '')}</span>"
        
        # 背面：中文 + 俄语 (换行)
        meaning_field = f"🇨🇳 {item.get('zh', '')} <br> 🇷🇺 {item.get('ru', '')}"
        
        # 音频字段
        audio_field = f"[sound:{audio_filename}]" if audio_filename else ""

        # 3. 添加笔记
        note = genanki.Note(
            model=my_model,
            fields=[word_field, meaning_field, audio_field]
        )
        deck.add_note(note)
        
        progress_bar.progress((idx + 1) / len(selected_items))

    # 打包
    status_text.text("正在打包 .apkg 文件...")
    output_package = genanki.Package(deck)
    output_package.media_files = media_files
    
    # 写入内存流
    pkg_bytes = io.BytesIO()
    # genanki 需要写临时文件
    temp_pkg_name = "temp_anki_output.apkg"
    output_package.write_to_file(temp_pkg_name)
    
    with open(temp_pkg_name, "rb") as f:
        final_bytes = f.read()
    
    # 清理临时文件
    os.remove(temp_pkg_name)
    for f in media_files:
        if os.path.exists(f): os.remove(f)
        
    progress_bar.empty()
    status_text.empty()
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

st.title("🦋 跟读助手 (V11.0)")

if 'vocab_book' not in st.session_state: st.session_state.vocab_book = load_vocab()
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'audio_cache' not in st.session_state: st.session_state.audio_cache = None
if 'translation_result' not in st.session_state: st.session_state.translation_result = ""
if 'temp_word_audio' not in st.session_state: st.session_state.temp_word_audio = {}

with st.sidebar:
    st.header("⚙️ 设置")
    
    # Key (不保存到本地文件)
    default_key = st.session_state.app_config.get("api_key", "")
    api_input = st.text_input("SiliconFlow Key", value=default_key, type="password")
    if api_input != st.session_state.app_config.get("api_key"):
        st.session_state.app_config["api_key"] = api_input

    st.divider()
    tts_engine = st.radio("🔊 语音引擎", ["Edge (推荐/免费)", "SiliconFlow (付费)"], index=0)
    
    voice_id = "default"
    if tts_engine == "SiliconFlow (付费)":
        st.info("💎 CosyVoice2 (支持倍速)")
        voice_choice = st.selectbox("🎙️ 选择音色", list(VOICE_MAP_SF.keys()))
        voice_id = VOICE_MAP_SF[voice_choice]
        
    elif tts_engine == "Edge (推荐/免费)":
        lang_choice_temp = st.selectbox("🌍 语言预览", list(VOICE_MAP_EDGE.keys()), index=0, key="edge_lang_prev")
        available_voices = VOICE_MAP_EDGE[lang_choice_temp]
        voice_id = st.radio("🎙️ 音色", [v[0] for v in available_voices], format_func=lambda x: next(v[1] for v in available_voices if v[0] == x))

    st.divider()
    lang_choice = st.selectbox("🌍 学习语言", list(VOICE_MAP_EDGE.keys()), index=0)
    speed_int = st.slider("🐇 语速调节", -50, 50, 0, 5, help="Edge: 百分比 | CosyVoice: 0.5x-1.5x")
    
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
                # 🔥 传入 speed_int
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
                    # 显示 IPA
                    if item.get('ipa'): st.caption(f"[{item['ipa']}]")
                    if st.button("🔊", key=f"p_{item['word']}_{d}_{idx}"):
                        # 🔥 单词播放也传入 speed_int
                        ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], tts_engine, voice_id, speed_int, st.session_state.app_config))
                        if ab: st.session_state.temp_word_audio[item['word']] = ab; st.rerun()
                with c_ph:
                    st.markdown(f"🇨🇳 {item.get('zh','')}")
                    # 显示俄语
                    st.markdown(f"🇷🇺 {item.get('ru','')}")
                
                if item['word'] in st.session_state.temp_word_audio:
                    st.audio(st.session_state.temp_word_audio[item['word']], autoplay=True)
                    del st.session_state.temp_word_audio[item['word']]
            st.divider()

        if checked_items:
            st.info(f"选中 {len(checked_items)} 个单词")
            col_exp, col_del = st.columns(2)
            with col_exp:
                if st.button("📤 导出Anki (带音频)"):
                    with st.spinner("正在生成Anki包 (包含音频)..."):
                        # 🔥 传入所有配置参数，确保Anki音频和当前设置一致
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
