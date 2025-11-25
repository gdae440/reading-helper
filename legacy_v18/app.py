import streamlit as st
from openai import OpenAI
import edge_tts
from gtts import gTTS
import asyncio
import json
import os
import io
import base64
import re 
from datetime import datetime
from PIL import Image
import genanki
from streamlit_option_menu import option_menu 
import random 

# ================= 1. 核心函数 & 配置加载 =================

def load_config():
    return {
        "api_key": "", 
        "engine": "Edge (推荐)", 
        "voice_role": "en-GB-RyanNeural", 
        "speed": 0, 
        "learn_lang": "🇬🇧 英语",
        "chat_model": "deepseek-ai/DeepSeek-V3", 
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "generic_api_key": "" 
    }

def load_vocab():
    VOCAB_FILE = "my_vocab.json"
    if os.path.exists(VOCAB_FILE):
        try: return json.load(open(VOCAB_FILE, "r", encoding="utf-8"))
        except: return []
    return []

def get_smart_filename(text):
    if not text: return f"read_aloud_{datetime.now().strftime('%H%M%S')}.mp3"
    snippet = text[:50]
    safe_name = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', snippet)
    safe_name = re.sub(r'[\s]+', '_', safe_name).strip()
    if not safe_name: return f"read_aloud_{datetime.now().strftime('%H%M%S')}.mp3"
    return f"{safe_name}.mp3"

# ================= 2. 状态管理 =================

st.set_page_config(page_title="跟读助手 Pro (V18.2)", layout="wide", page_icon="🦋")

if 'cfg' not in st.session_state: 
    init_cfg = load_config()
    env_key = os.getenv("SILICON_KEY")
    if env_key: init_cfg["api_key"] = env_key
    try:
        if "SILICON_KEY" in st.secrets: init_cfg["api_key"] = st.secrets["SILICON_KEY"]
    except: pass
    st.session_state.cfg = init_cfg

if 'vocab' not in st.session_state: st.session_state.vocab = load_vocab()
if 'main_text' not in st.session_state: st.session_state.main_text = ""
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'last_lookup' not in st.session_state: st.session_state.last_lookup = None
if 'temp_audio' not in st.session_state: st.session_state.temp_audio = {}

# ================= 3. 视觉系统 (CSS Magic) =================

LANG_COLORS_MAP = {
    "🇬🇧 英语": {"border": "#007AFF", "bg": "#F2F9FF"}, 
    "🇫🇷 法语": {"border": "#AF52DE", "bg": "#Fbf2ff"}, 
    "🇩🇪 德语": {"border": "#34C759", "bg": "#F2fff5"}, 
    "🇷🇺 俄语": {"border": "#FF9500", "bg": "#FFF8F0"}, 
}

def get_current_colors():
    lang = st.session_state.cfg.get("learn_lang", "🇬🇧 英语")
    return LANG_COLORS_MAP.get(lang, LANG_COLORS_MAP["🇬🇧 英语"])

# V18.2: 修复 OptionMenu 暗黑模式背景色问题
st.markdown(f"""
<style>
    html, body, [class*="css"] {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    /* 按钮美化 - 强制深色文字适配暗黑模式 */
    .stButton > button {{
        background-color: #ffffff !important;
        color: #333333 !important;
        border: 1px solid #d1d1d6;
        border-radius: 12px;
        padding: 0.5rem 1rem;
        font-weight: 500;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }}
    .stButton > button:hover {{
        border-color: #007AFF;
        color: #007AFF !important;
        background-color: #F2F9FF !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transform: translateY(-1px);
    }}
    /* 主按钮 */
    div[data-testid="stVerticalBlock"] > div > button[kind="primary"] {{
        background: linear-gradient(180deg, #007AFF 0%, #0062cc 100%) !important;
        color: white !important;
        border: none;
        box-shadow: 0 2px 4px rgba(0,122,255,0.3);
    }}
    /* 卡片样式 - 强制内部文字深色 */
    div.custom-card {{
        border: 1px solid {get_current_colors()['border']}; 
        border-radius: 16px; 
        padding: 20px;
        background-color: {get_current_colors()['bg']}; 
        color: #333333 !important;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.06); 
        margin-bottom: 15px;
        transition: transform 0.2s;
    }}
    div.custom-card p, div.custom-card span, div.custom-card div {{
        color: #333333 !important;
    }}
    div.custom-card:hover {{ transform: scale(1.01); }}
    
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .css-1d3w5wq {{ padding-left: 20px; padding-right: 20px; }}
</style>
""", unsafe_allow_html=True)

for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

VOCAB_FILE = "my_vocab.json"

VOICE_MAP_EDGE = {
    "🇬🇧 英语": [("en-GB-RyanNeural", "Ryan (英/男)"), ("en-US-ChristopherNeural", "Chris (美/男)"), ("en-US-AriaNeural", "Aria (美/女)")],
    "🇫🇷 法语": [("fr-FR-HenriNeural", "Henri (法/男)"), ("fr-FR-DeniseNeural", "Denise (法/女)")],
    "🇩🇪 德语": [("de-DE-ConradNeural", "Conrad (德/男)"), ("de-DE-KatjaNeural", "Katja (德/女)")],
    "🇷🇺 俄语": [("ru-RU-DmitryNeural", "Dmitry (俄/男)"), ("ru-RU-SvetlanaNeural", "Svetlana (俄/女)")],
}
VOICE_MAP_SF = {
    "男声 - Benjamin (英伦风)": "FunAudioLLM/CosyVoice2-0.5B:benjamin", 
    "男声 - Alex (沉稳)": "FunAudioLLM/CosyVoice2-0.5B:alex",
    "女声 - Bella (温柔)": "FunAudioLLM/CosyVoice2-0.5B:bella",
    "女声 - Claire (清晰)": "FunAudioLLM/CosyVoice2-0.5B:claire"
}
LANG_MAP_GOOGLE = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru"}

# ================= 4. 辅助功能 =================

def save_vocab(vocab_list):
    try: json.dump(vocab_list, open(VOCAB_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except: pass

def compress_image(image):
    image.thumbnail((1024, 1024)); buffered = io.BytesIO(); image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, api_key):
    if "Edge" in engine_type:
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=f"{speed_int:+d}%")
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge Error: {e}"
    elif "SiliconFlow" in engine_type:
        if not api_key: return None, "No API Key"
        client = OpenAI(api_key=api_key, base_url="[https://api.siliconflow.cn/v1](https://api.siliconflow.cn/v1)")
        model_id = voice_id.split(":")[0] if ":" in voice_id else "FunAudioLLM/CosyVoice2-0.5B"
        try:
            sf_speed = 1.0 + (speed_int / 100.0)
            response = client.audio.speech.create(model=model_id, voice=voice_id, input=text, speed=sf_speed)
            return response.content, None
        except Exception as e: return None, f"SF Error: {e}"
    elif "Google" in engine_type:
        try:
            tts = gTTS(text=text, lang=voice_id)
            mp3_fp = io.BytesIO(); tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Google Error: {e}"
    return None, "Unknown Engine"

async def create_anki_package(selected_items, engine_type, voice_id, speed_int, api_key):
    deck = genanki.Deck(random.randrange(1<<30, 1<<31), '跟读助手生词本')
    model = genanki.Model(random.randrange(1<<30, 1<<31), 'Simple Model', 
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{'name': 'Card 1', 'qfmt': '{{Question}}<br>{{Audio}}', 'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}'}])
    media = []
    bar = st.progress(0, text="打包中...")
    
    for i, item in enumerate(selected_items):
        bar.progress((i+1)/len(selected_items), text=f"处理: {item['word']}")
        aud, _ = await get_audio_bytes_mixed(item['word'], engine_type, voice_id, speed_int, api_key)
        fname = ""
        if aud:
            fname = f"anki_{random.randint(1000,9999)}_{i}.mp3"
            with open(fname, "wb") as f: f.write(aud)
            media.append(fname)
        deck.add_note(genanki.Note(model=model, fields=[
            f"{item['word']} <br> <small style='color:grey'>{item.get('ipa','')}</small>",
            f"🇨🇳 {item.get('zh','')}<br>🇷🇺 {item.get('ru','')}",
            f"[sound:{fname}]" if fname else ""
        ]))
    
    pkg = genanki.Package(deck); pkg.media_files = media
    pkg.write_to_file("temp.apkg")
    with open("temp.apkg", "rb") as f: b = f.read()
    os.remove("temp.apkg")
    for m in media: 
        if os.path.exists(m): os.remove(m)
    bar.empty()
    return b

def api_call(type, content, api_key):
    client = OpenAI(api_key=api_key, base_url="[https://api.siliconflow.cn/v1](https://api.siliconflow.cn/v1)")
    ocr_model = st.session_state.cfg.get("ocr_model", "Qwen/Qwen2.5-VL-72B-Instruct")
    chat_model = st.session_state.cfg.get("chat_model", "deepseek-ai/DeepSeek-V3")

    try:
        if type == "ocr":
            b64 = compress_image(content)
            res = client.chat.completions.create(model=ocr_model, messages=[{"role": "user", "content": [{"type": "text", "text": "OCR text only. Keep formatting."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}])
            return res.choices[0].message.content, None
        elif type == "lookup":
            prompt = f"""Dictionary API. User input: "{content}". Return JSON: {{ "detected_lang": "...", "ipa": "...", "zh": "...", "ru": "..." }} (Concise)"""
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            return json.loads(res.choices[0].message.content), None
        elif type == "trans":
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": f"Translate to Chinese:\n{content}"}])
            return res.choices[0].message.content, None
    except Exception as e: 
        if "authentication" in str(e).lower():
            return None, f"API 认证失败。请检查 Key。"
        return None, f"API 调用失败 ({type}/{chat_model}): {str(e)}"

# ================= 5. UI 界面 =================

with st.sidebar:
    st.caption("🦋 跟读助手 Pro (V18.2)")

# V18.2 修复: 导航栏背景设为透明，适配暗黑模式
selected = option_menu(
    menu_title=None,
    options=["学习主页", "单词本", "设置"],
    icons=["house", "book", "gear"],
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {"padding": "0!important", "background-color": "transparent"}, 
        "icon": {"color": get_current_colors()['border'], "font-size": "18px"}, 
        "nav-link-selected": {"background-color": get_current_colors()['bg']}, 
    }
)

# --- 1. 设置页面 ---
if selected == "设置":
    st.header("⚙️ 全局设置")
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("🔑 API & 模型")
        new_k = st.text_input("SiliconFlow Key", value=st.session_state.cfg["api_key"], type="password", help="必填")
        if new_k != st.session_state.cfg["api_key"]: st.session_state.cfg["api_key"] = new_k

        new_gen_k = st.text_input("其他 API Key", value=st.session_state.cfg.get("generic_api_key", ""), type="password")
        if new_gen_k != st.session_state.cfg.get("generic_api_key", ""): st.session_state.cfg["generic_api_key"] = new_gen_k

        st.markdown("---")
        st.caption("高级: 自定义模型")

        new_chat_model = st.text_input("Chat 模型", value=st.session_state.cfg["chat_model"])
        if new_chat_model != st.session_state.cfg["chat_model"]: st.session_state.cfg["chat_model"] = new_chat_model
        
        new_ocr_model = st.text_input("OCR 模型", value=st.session_state.cfg["ocr_model"])
        if new_ocr_model != st.session_state.cfg["ocr_model"]: st.session_state.cfg["ocr_model"] = new_ocr_model

    with c2: 
        st.subheader("🔊 语音配置")
        
        lang_options = list(VOICE_MAP_EDGE.keys())
        try: lang_idx = lang_options.index(st.session_state.cfg["learn_lang"])
        except: lang_idx = 0
        new_lang = st.selectbox("🌍 学习目标语言", lang_options, index=lang_idx)
        st.session_state.cfg["learn_lang"] = new_lang
        
        tts_options = ["Edge (推荐)", "SiliconFlow", "Google"]
        try: eng_idx = tts_options.index(st.session_state.cfg["engine"])
        except: eng_idx = 0
        new_engine = st.selectbox("🔊 语音引擎", tts_options, index=eng_idx)
        st.session_state.cfg["engine"] = new_engine
        
        new_speed = st.slider("🐇 语速调节", -50, 50, value=st.session_state.cfg["speed"], step=5)
        st.session_state.cfg["speed"] = new_speed
        
        st.divider()
        st.caption("🎙️ 音色选择")
        
        eng = st.session_state.cfg["engine"]
        lang = st.session_state.cfg["learn_lang"]
        
        if "Edge" in eng:
            vs = VOICE_MAP_EDGE[lang]
            try: v_idx = [v[0] for v in vs].index(st.session_state.cfg["voice_role"])
            except: v_idx = 0
            new_role = st.radio("Edge 音色", [v[0] for v in vs], format_func=lambda x: next(v[1] for v in vs if v[0]==x), index=v_idx)
            st.session_state.cfg["voice_role"] = new_role
        elif "Google" in eng:
            st.info("Google TTS 音色自动匹配。")
            st.session_state.cfg["voice_role"] = LANG_MAP_GOOGLE.get(lang, "en")
        elif "Silicon" in eng:
            sf_keys = list(VOICE_MAP_SF.keys())
            try: sf_idx = sf_keys.index(next(k for k, v in VOICE_MAP_SF.items() if v == st.session_state.cfg["voice_role"]))
            except: sf_idx = 0
            v_choice = st.selectbox("CosyVoice 音色", sf_keys, index=sf_idx)
            st.session_state.cfg["voice_role"] = VOICE_MAP_SF[v_choice]

# --- 2. 学习主页 ---
elif selected == "学习主页":
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        st.caption("📥 学习素材")
        mode = st.radio("Mode", ["文本", "图片OCR"], horizontal=True, label_visibility="collapsed")
        if mode == "文本":
            txt = st.text_area("在此粘贴文本...", height=120)
            if st.button("确认文本", use_container_width=True):
                st.session_state.main_text = txt; st.session_state.audio_data = None; st.rerun()
        else:
            up = st.file_uploader("Upload", type=['jpg','png'], label_visibility="collapsed")
            if up and st.button("开始识别", use_container_width=True):
                res, err = api_call("ocr", Image.open(up), st.session_state.cfg["api_key"])
                if res: st.session_state.main_text = res; st.session_state.audio_data = None; st.rerun()
                else: st.error(err)
        
        if st.session_state.main_text:
            st.divider()
            st.subheader("文章朗读区")
            with st.container(border=True): 
                st.markdown(f"{st.session_state.main_text}", unsafe_allow_html=True)
            
            if st.button("▶️ 生成并播放全文", type="primary", use_container_width=True):
                with st.spinner("Generating..."):
                    ab, err = asyncio.run(get_audio_bytes_mixed(st.session_state.main_text, st.session_state.cfg["engine"], st.session_state.cfg["voice_role"], st.session_state.cfg["speed"], st.session_state.cfg["api_key"]))
                    if ab: st.session_state.audio_data = ab; st.rerun()
                    else: st.error(err)
            
            if st.session_state.audio_data: 
                st.audio(st.session_state.audio_data, format='audio/mpeg')
                safe_filename = get_smart_filename(st.session_state.main_text)
                st.download_button(
                    label=f"⬇️ 下载: {safe_filename}",
                    data=st.session_state.audio_data,
                    file_name=safe_filename,
                    mime="audio/mpeg",
                    use_container_width=True
                )

    with col_r:
        st.caption("🔍 查词并保存")
        q_w = st.text_input("Word", label_visibility="collapsed")
        if st.button("查询", use_container_width=True):
            if not st.session_state.cfg["api_key"]: st.error("Need API Key")
            else:
                info, err = api_call("lookup", q_w, st.session_state.cfg["api_key"])
                if info:
                    st.session_state.vocab.insert(0, {"word": q_w, "lang": st.session_state.cfg["learn_lang"], "date": datetime.now().strftime("%Y-%m-%d"), **info})
                    save_vocab(st.session_state.vocab)
                    st.session_state.last_lookup = info
                    st.session_state.last_lookup["word"] = q_w
                    st.rerun()

        if st.session_state.last_lookup:
            ll = st.session_state.last_lookup
            st.markdown(f"""
            <div class="custom-card">
                <p style="margin-top:0;">
                    <span style="font-size: 1.3em; font-weight: 600;">{ll['word']}</span>
                </p>
                <div style="font-size: 0.95em; line-height: 1.6;">
                    <div style="margin-bottom:4px;"><b>音标：</b> <span style='color:#666; font-family: "Arial", sans-serif;'>[{ll.get('ipa','--')}]</span></div>
                    <div style="margin-bottom:4px;"><b>中文：</b> {ll.get('zh','--')}</div>
                    <div><b>俄语：</b> {ll.get('ru','--')}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🔊 试听发音", key="play_lookup", use_container_width=True):
                ab, _ = asyncio.run(get_audio_bytes_mixed(ll['word'], st.session_state.cfg["engine"], st.session_state.cfg["voice_role"], st.session_state.cfg["speed"], st.session_state.cfg["api_key"]))
                if ab: st.session_state.temp_audio["lookup"] = ab; st.rerun()

            if "lookup" in st.session_state.temp_audio and isinstance(st.session_state.temp_audio["lookup"], bytes):
                 st.audio(st.session_state.temp_audio["lookup"], format="audio/mpeg", autoplay=True)
                 del st.session_state.temp_audio["lookup"]

# --- 3. 单词本 ---
elif selected == "单词本":
    cur_vocab = [v for v in st.session_state.vocab if v.get('lang', '🇬🇧 英语') == st.session_state.cfg["learn_lang"]]
    
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1: st.info(f"📚 总词条数: {len(st.session_state.vocab)} 个", icon="📖") 
    with col_stat2: st.success(f"📌 当前语言 ({st.session_state.cfg['learn_lang']}) : {len(cur_vocab)} 个", icon="✅")
    with col_stat3:
        if st.button("⚠️ 清空当前语言词表", use_container_width=True):
            st.session_state.vocab = [v for v in st.session_state.vocab if v.get('lang') != st.session_state.cfg["learn_lang"]]
            save_vocab(st.session_state.vocab)
            st.rerun()
    
    st.divider()

    if not cur_vocab:
        st.info("当前语言暂无单词")
    else:
        h1, h2, h3, h4 = st.columns([0.5, 2, 4, 1])
        h1.markdown("✅")
        h2.markdown("**单词/音标**")
        h3.markdown("**释义 (中/俄)**")
        h4.markdown("**发音**")
        
        checked_items = []
        for idx, item in enumerate(cur_vocab):
            with st.container():
                r1, r2, r3, r4 = st.columns([0.5, 2, 4, 1])
                with r1:
                    if st.checkbox("", key=f"chk_real_{idx}"): checked_items.append(item)
                with r2:
                    st.markdown(f"**{item['word']}**")
                    st.caption(f"{item.get('ipa','')}")
                with r3:
                    st.markdown(f"🇨🇳 {item.get('zh','')}") 
                    st.markdown(f"🇷🇺 {item.get('ru','')}")
                with r4:
                    if st.button("🔊", key=f"v_play_{idx}"):
                        ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], st.session_state.cfg["engine"], st.session_state.cfg["voice_role"], st.session_state.cfg["speed"], st.session_state.cfg["api_key"]))
                        if ab: st.session_state.temp_audio[item['word']] = ab; st.rerun()
                
                if item['word'] in st.session_state.temp_audio:
                    st.audio(st.session_state.temp_audio[item['word']], format="audio/mpeg", autoplay=True)
                    del st.session_state.temp_audio[item['word']]
                
                st.divider() 

        if checked_items:
            st.success(f"已选中 {len(checked_items)} 个单词")
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                if st.button("📤 导出选中至 Anki"):
                    with st.spinner("打包中..."):
                        pkg = asyncio.run(create_anki_package(checked_items, st.session_state.cfg["engine"], st.session_state.cfg["voice_role"], st.session_state.cfg["speed"], st.session_state.cfg["api_key"]))
                        st.download_button("⬇️ 下载 .apkg", pkg, file_name=f"anki_select_{len(checked_items)}.apkg")
            with b_col2:
                if st.button("🗑️ 删除选中单词"):
                    rem_words = [i['word'] for i in checked_items]
                    st.session_state.vocab = [v for v in st.session_state.vocab if v['word'] not in rem_words]
                    save_vocab(st.session_state.vocab)
                    st.rerun()