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
import random
import time
from datetime import datetime
from PIL import Image
import genanki
from streamlit_option_menu import option_menu

# ================= 1. 核心配置与工具函数 =================

VOCAB_FILE = "my_vocab.json"

def load_vocab():
    """加载生词本"""
    paths = ["my_vocab.json", "../my_vocab.json"]
    for p in paths:
        if os.path.exists(p):
            try:
                return json.load(open(p, "r", encoding="utf-8"))
            except: pass
    return []

def save_vocab(vocab_list):
    """保存生词本"""
    try:
        with open(VOCAB_FILE, "w", encoding="utf-8") as f:
            json.dump(vocab_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"保存失败: {e}")

def get_smart_filename(text):
    """生成文件名"""
    if not text: return "audio.mp3"
    snippet = text[:20]
    safe_name = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', snippet).strip()
    return f"{safe_name}.mp3" if safe_name else "audio.mp3"

def auto_detect_language(text):
    """简单的语言自动检测 (无需额外依赖)"""
    if not text: return None
    # 检测西里尔字母 -> 俄语
    if re.search(r'[\u0400-\u04FF]', text):
        return "🇷🇺 俄语"
    # 检测汉字 -> 中文 (通常作为母语或学习对象)
    elif re.search(r'[\u4e00-\u9fa5]', text):
        # 这里假设如果是中文文章，可能不需要朗读，或者是想用中文语音
        # 暂时不自动切到中文，除非有特殊需求。
        # 我们的目标语言列表中没有中文，所以暂时忽略，或默认为英语
        pass 
    # 检测法语/德语特殊字符 (简单判断)
    elif re.search(r'[àâäéèêëîïôöùûüçß]', text, re.IGNORECASE):
        # 这种判断比较粗糙，但在中/英/俄环境下足够区分俄语
        # 如果是德语/法语混合很难区分，这里优先不做误判
        pass
    return "🇬🇧 英语" # 默认

# ================= 2. 页面初始化与样式 =================

st.set_page_config(page_title="跟读助手 Pro", layout="wide", page_icon="📘")

st.markdown("""
<style>
    :root {
        --bg-color: #f5f5f7;
        --text-color: #000000;
        --card-bg-color: #ffffff;
        --card-border-color: #e5e5ea;
        --primary-color: #007aff;
        --secondary-text-color: #666;
        --shadow-color: rgba(0,0,0,0.1);
        --shadow-color-light: rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-color: #1c1c1e;
            --text-color: #ffffff;
            --card-bg-color: #2c2c2e;
            --card-border-color: #3a3a3c;
            --primary-color: #0a84ff;
            --secondary-text-color: #8e8e93;
            --shadow-color: rgba(255,255,255,0.1);
            --shadow-color-light: rgba(255,255,255,0.05);
        }
    }
    .stApp {
        background-color: var(--bg-color);
        color: var(--text-color);
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .stButton > button {
        border-radius: 10px;
        border: none;
        font-weight: 500;
        transition: 0.2s;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px var(--shadow-color);
    }
    div.lookup-card {
        background: var(--card-bg-color);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 10px var(--shadow-color-light);
        margin-bottom: 15px;
        border: 1px solid var(--card-border-color);
        color: var(--text-color);
    }
    .lookup-card h3 {
        color: var(--primary-color) !important;
    }
    .lookup-card div {
        color: var(--text-color) !important;
    }
    .lookup-card div[style*="color:#666"] {
        color: var(--secondary-text-color) !important;
    }
</style>
""", unsafe_allow_html=True)

# ================= 3. 状态管理 =================

if 'cfg' not in st.session_state:
    st.session_state.cfg = {
        "api_key": os.getenv("SILICON_KEY", ""),
        "engine": "Edge (推荐)",
        "voice_role": "en-US-AriaNeural",
        "speed": 0,
        "learn_lang": "🇬🇧 英语",
        "chat_model": "deepseek-ai/DeepSeek-V3",
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "generic_base_url": "https://api.siliconflow.cn/v1"
    }

if 'vocab' not in st.session_state: st.session_state.vocab = load_vocab()
if 'main_text' not in st.session_state: st.session_state.main_text = ""
if 'trans_text' not in st.session_state: st.session_state.trans_text = ""
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
# 增加时间戳 key 强制刷新播放器
if 'audio_timestamp' not in st.session_state: st.session_state.audio_timestamp = 0 
if 'last_lookup' not in st.session_state: st.session_state.last_lookup = None
if 'lookup_audio' not in st.session_state: st.session_state.lookup_audio = None
if 'lookup_audio_ts' not in st.session_state: st.session_state.lookup_audio_ts = 0

# ================= 4. 核心逻辑 =================

def get_api_client(cfg):
    key = cfg.get("api_key")
    base_url = cfg.get("generic_base_url", "https://api.siliconflow.cn/v1")
    if not key: return None, "❌ 未配置 API Key"
    if not base_url.endswith("/v1"): 
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAI(api_key=key, base_url=base_url), None

def api_call(task_type, content, cfg):
    client, err = get_api_client(cfg)
    if not client: return None, err

    try:
        if task_type == "ocr":
            buffered = io.BytesIO()
            content.save(buffered, format="JPEG", quality=85)
            b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            res = client.chat.completions.create(
                model=cfg["ocr_model"],
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "OCR raw text output only. No markdown."}, 
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}]
            )
            return res.choices[0].message.content, None
        elif task_type == "lookup":
            prompt = f"""Explain '{content}' concisely. Format strictly as valid JSON:
            {{ "word": "{content}", "ipa": "/.../", "zh": "中文释义", "ru": "俄语释义 (if applicable)" }}"""
            res = client.chat.completions.create(
                model=cfg["chat_model"],
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(res.choices[0].message.content), None
        elif task_type == "trans":
            res = client.chat.completions.create(
                model=cfg["chat_model"],
                messages=[{"role": "user", "content": f"Translate to natural Chinese:\n{content}"}]
            )
            return res.choices[0].message.content, None
    except Exception as e:
        return None, str(e)
    return None, "Unknown"

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, cfg):
    """TTS 核心生成, 带回退机制"""
    if not text.strip():
        return None, "❌ Text cannot be empty."

    # 1. Primary Engine: Edge TTS
    async def try_edge_tts():
        try:
            rate_str = f"{speed_int:+d}%"
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            mp3_fp = io.BytesIO()
            audio_received = False
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_fp.write(chunk["data"])
                    audio_received = True
            if not audio_received:
                return None, "Edge Error: No audio was received."
            return mp3_fp.getvalue(), None
        except Exception as e:
            return None, f"Edge Error: {e}"

    # 2. Fallback/Alternative: gTTS
    def try_gtts():
        try:
            lang_map = { "🇬🇧 英语": "en", "🇷🇺 俄语": "ru", "🇫🇷 法语": "fr", "🇩🇪 德语": "de" }
            lang_code = lang_map.get(cfg.get("learn_lang", "🇬🇧 英语"), "en")

            mp3_fp = io.BytesIO()
            tts = gTTS(text, lang=lang_code)
            tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e:
            return None, f"gTTS Error: {e}"

    # 3. Alternative: OpenAI TTS
    def try_openai_tts():
        try:
            client, err = get_api_client(cfg)
            if not client: return None, err

            openai_voice = "nova" # Default female voice
            if "Ryan" in voice_id or "Dmitry" in voice_id or "Henri" in voice_id or "Conrad" in voice_id:
                openai_voice = "echo" # Switch to a male voice

            speed_float = max(0.25, min(4.0, 1.0 + (speed_int / 100.0)))

            response = client.audio.speech.create(model="tts-1", voice=openai_voice, speed=speed_float, input=text)
            return response.content, None
        except Exception as e:
            return None, f"OpenAI TTS Error: {e}"

    # Main Logic
    if "Edge TTS" in engine_type:
        audio, err = await try_edge_tts()
        if audio:
            return audio, None
        st.warning("⚠️ Edge TTS failed, falling back to gTTS...")
        return try_gtts()

    elif "OpenAI TTS" in engine_type:
        return try_openai_tts()

    elif "gTTS" in engine_type:
        return try_gtts()

    return None, "Unsupported Engine"

async def create_anki_package(selected_items, cfg):
    """Anki 导出核心"""
    deck = genanki.Deck(random.randrange(1<<30, 1<<31), '跟读助手生词本')
    model = genanki.Model(1607392319, 'Simple Model', fields=[{'name': 'Q'}, {'name': 'A'}, {'name': 'Media'}],
        templates=[{'name': 'Card', 'qfmt': '{{Q}}<br>{{Media}}', 'afmt': '{{FrontSide}}<hr>{{A}}'}])
    media, temp_paths = [], []
    
    for item in selected_items:
        v_role = "ru-RU-DmitryNeural" if "ru" in str(item) else "en-US-AriaNeural"
        aud, _ = await get_audio_bytes_mixed(item['word'], "Edge (推荐)", v_role, 0, cfg)
        fname = ""
        if aud:
            fname = f"anki_{random.randint(10000,99999)}.mp3"
            with open(fname, "wb") as f: f.write(aud)
            media.append(fname); temp_paths.append(fname)
        
        deck.add_note(genanki.Note(model=model, fields=[
            f"{item['word']} <span style='color:grey'>[{item.get('ipa','')}]</span>",
            f"🇨🇳 {item.get('zh','')}<br>🇷🇺 {item.get('ru','')}",
            f"[sound:{fname}]" if fname else ""
        ]))
    
    out = io.BytesIO()
    genanki.Package(deck, media_files=media).write_to_file(out)
    for p in temp_paths: os.remove(p)
    out.seek(0)
    return out

# ================= 5. 侧边栏 =================

with st.sidebar:
    st.title("Reading Pro")
    page = option_menu(None, ["学习主页", "单词本", "设置"], icons=['book', 'bookmark', 'gear'])
    
    st.divider()
    
    # 自动语言同步逻辑
    lang_map = {
        "🇬🇧 英语": {"default": "en-US-AriaNeural", "voices": {"🇺🇸 Aria": "en-US-AriaNeural", "🇬🇧 Ryan": "en-GB-RyanNeural"}},
        "🇷🇺 俄语": {"default": "ru-RU-DmitryNeural", "voices": {"🇷🇺 Dmitry": "ru-RU-DmitryNeural", "🇷🇺 Svetlana": "ru-RU-SvetlanaNeural"}},
        "🇫🇷 法语": {"default": "fr-FR-HenriNeural", "voices": {"🇫🇷 Henri": "fr-FR-HenriNeural", "🇫🇷 Denise": "fr-FR-DeniseNeural"}},
        "🇩🇪 德语": {"default": "de-DE-ConradNeural", "voices": {"🇩🇪 Conrad": "de-DE-ConradNeural"}}
    }
    
    # 渲染语言选择器
    lang_list = list(lang_map.keys())
    curr_lang = st.session_state.cfg.get("learn_lang", "🇬🇧 英语")
    
    # 如果检测到 text 变化，这里尝试自动跳转
    if st.session_state.main_text:
        detected = auto_detect_language(st.session_state.main_text)
        # 只有当检测出的语言在列表里，且和当前不同，才自动切换
        if detected in lang_list and detected != curr_lang:
            curr_lang = detected
            st.session_state.cfg["learn_lang"] = detected
            st.session_state.cfg["voice_role"] = lang_map[detected]["default"]
            st.toast(f"🔍 已自动切换到: {detected}")

    sel_lang = st.selectbox("目标语言", lang_list, index=lang_list.index(curr_lang) if curr_lang in lang_list else 0)
    
    # 如果用户手动改了 Dropdown
    if sel_lang != st.session_state.cfg["learn_lang"]:
        st.session_state.cfg["learn_lang"] = sel_lang
        st.session_state.cfg["voice_role"] = lang_map[sel_lang]["default"]
        st.rerun()
        
    # 渲染音色选择
    curr_voices_dict = lang_map[st.session_state.cfg["learn_lang"]]["voices"]
    v_names = list(curr_voices_dict.keys())
    
    # 反查当前 voice name
    curr_v_code = st.session_state.cfg.get("voice_role")
    curr_v_name = v_names[0]
    for name, code in curr_voices_dict.items():
        if code == curr_v_code: curr_v_name = name
        
    sel_v_name = st.selectbox("发音人", v_names, index=v_names.index(curr_v_name) if curr_v_name in v_names else 0)
    st.session_state.cfg["voice_role"] = curr_voices_dict[sel_v_name]
    
    st.session_state.cfg["speed"] = st.slider("语速", -50, 50, st.session_state.cfg["speed"], 10)

    engine_options = ["Edge TTS", "OpenAI TTS", "gTTS"]
    current_engine = st.session_state.cfg.get("engine", "Edge TTS")
    try:
        default_index = engine_options.index(current_engine)
    except ValueError:
        default_index = 0 # Default to "Edge TTS" if the old value is not found

    st.session_state.cfg["engine"] = st.selectbox("语音引擎",
        engine_options,
        index=default_index
    )

# ================= 6. 主页面逻辑 =================

if page == "学习主页":
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("📝 原文")
        # 修复：直接绑定 session_state，无需 Update 按钮
        st.session_state.main_text = st.text_area("Input", value=st.session_state.main_text, height=250, label_visibility="collapsed", placeholder="在此粘贴文章...")
        
        # 操作区
        if st.session_state.main_text:
            col_ops = st.columns([1, 1, 2])
            with col_ops[0]:
                if st.button("▶️ 朗读", type="primary", use_container_width=True):
                    with st.spinner("生成语音..."):
                        ab, err = asyncio.run(get_audio_bytes_mixed(
                            st.session_state.main_text,
                            st.session_state.cfg["engine"],
                            st.session_state.cfg["voice_role"],
                            st.session_state.cfg["speed"],
                            st.session_state.cfg
                        ))
                        if ab: 
                            st.session_state.audio_data = ab
                            st.session_state.audio_timestamp = time.time() # 强制刷新
                            st.rerun()
                        else: st.error(err)
            
            with col_ops[1]:
                if st.button("🌐 翻译", use_container_width=True):
                    with st.spinner("翻译中..."):
                        res, err = api_call("trans", st.session_state.main_text, st.session_state.cfg)
                        if res: st.session_state.trans_text = res; st.rerun()
                        else: st.error(err)
            
            # 播放器渲染 (关键修复: 使用 key)
            if st.session_state.audio_data:
                st.audio(st.session_state.audio_data, format="audio/mp3", autoplay=True)
                # 下载链接
                b64 = base64.b64encode(st.session_state.audio_data).decode()
                fname = get_smart_filename(st.session_state.main_text)
                st.markdown(f'<a href="data:audio/mp3;base64,{b64}" download="{fname}" style="text-decoration:none;">📥 下载音频</a>', unsafe_allow_html=True)

            if st.session_state.trans_text:
                st.info(st.session_state.trans_text)

    with c2:
        st.subheader("🔍 查词")
        with st.container(border=True):
            q = st.text_input("Word", placeholder="输入单词...")
            if st.button("查询", use_container_width=True):
                if q:
                    with st.spinner("Looking up..."):
                        # 1. 查义
                        info, err = api_call("lookup", q, st.session_state.cfg)
                        if info:
                            st.session_state.last_lookup = info
                            # 2. 自动生成发音
                            # 查词发音始终用英语或根据单词检测
                            v_role = "en-US-AriaNeural"
                            if re.search(r'[\u0400-\u04FF]', q): v_role = "ru-RU-DmitryNeural"
                            
                            ab, _ = asyncio.run(get_audio_bytes_mixed(q, st.session_state.cfg["engine"], v_role, 0, st.session_state.cfg))
                            st.session_state.lookup_audio = ab
                            st.session_state.lookup_audio_ts = time.time() # 强制刷新
                            
                            # 3. 存入生词本
                            if not any(x['word'] == q for x in st.session_state.vocab):
                                st.session_state.vocab.insert(0, {**info, "date": datetime.now().strftime("%Y-%m-%d")})
                                save_vocab(st.session_state.vocab)
                            st.rerun()
                        else: st.error(err)

        if st.session_state.last_lookup:
            info = st.session_state.last_lookup

            # Custom container to simulate the card with the button inside
            st.markdown('<div class="lookup-card">', unsafe_allow_html=True)

            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"""
                    <h3 style="margin:0;">{info.get('word', '')}</h3>
                    <div style="color:var(--secondary-text-color); font-family:monospace;">[{info.get('ipa', '')}]</div>
                """, unsafe_allow_html=True)

            with col2:
                # This button is now inline with the word
                if st.button("🔊", key=f"play_lookup_{info.get('word')}"):
                    v_role = "en-US-AriaNeural"
                    if re.search(r'[\u0400-\u04FF]', info['word']):
                        v_role = "ru-RU-DmitryNeural"
                    ab, err = asyncio.run(get_audio_bytes_mixed(info['word'], st.session_state.cfg["engine"], v_role, 0, st.session_state.cfg))
                    if ab:
                        st.session_state.lookup_audio = ab
                        st.session_state.lookup_audio_ts = time.time()
                        st.rerun()
                    else:
                        st.error(err)

            st.markdown(f"""
                <hr style="margin:10px 0; border:none; border-top:1px solid var(--card-border-color);">
                <div><b>🇨🇳</b> {info.get('zh','')}</div>
                <div style="margin-top:5px"><b>🇷🇺</b> {info.get('ru','')}</div>
            """, unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)
            
            # 查词专用播放器 (不可见，仅自动播放)
            if st.session_state.lookup_audio:
                st.audio(st.session_state.lookup_audio, format="audio/mp3", autoplay=True)

elif page == "单词本":
    st.subheader(f"📓 生词本 ({len(st.session_state.vocab)})")
    if st.button("📤 导出 Anki 包"):
        sel = [v for i,v in enumerate(st.session_state.vocab) if st.session_state.get(f"chk_{i}", False)]
        if not sel: st.warning("请先勾选")
        else:
            dat = asyncio.run(create_anki_package(sel, st.session_state.cfg))
            st.download_button("⬇️ 下载 .apkg", dat, file_name="vocab.apkg")

    st.markdown("---")
    for i, item in enumerate(st.session_state.vocab):
        c1, c2, c3, c4, c5 = st.columns([0.5, 2, 3, 1, 1])
        c1.checkbox("", key=f"chk_{i}")
        c2.markdown(f"**{item['word']}**")
        c3.text(f"{item.get('zh','')} {item.get('ru','')}")
        if c4.button("🔊", key=f"v_play_{i}"):
            v_role = "en-US-AriaNeural"
            if re.search(r'[\u0400-\u04FF]', item['word']): v_role = "ru-RU-DmitryNeural"
            ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], st.session_state.cfg["engine"], v_role, 0, st.session_state.cfg))
            st.session_state.lookup_audio = ab
            st.session_state.lookup_audio_ts = time.time()
            st.rerun()
        if c5.button("🗑️", key=f"v_del_{i}"):
            st.session_state.vocab.pop(i)
            save_vocab(st.session_state.vocab)
            st.rerun()
            
    # 复用查词播放器
    if st.session_state.lookup_audio:
        st.audio(st.session_state.lookup_audio, format="audio/mp3", autoplay=True)

elif page == "设置":
    st.subheader("⚙️ 模型与接口配置")
    st.text_input("API Key", value=st.session_state.cfg["api_key"], type="password", key="key_input", on_change=lambda: st.session_state.cfg.update({"api_key": st.session_state.key_input}))
    st.text_input("Base URL", value=st.session_state.cfg["generic_base_url"], key="url_input", on_change=lambda: st.session_state.cfg.update({"generic_base_url": st.session_state.url_input}))

    st.divider()

    # LLM Model Selection
    chat_models = ["deepseek-ai/DeepSeek-V3"]
    selected_chat_model = st.selectbox(
        "LLM (Chat) Model",
        chat_models,
        index=chat_models.index(st.session_state.cfg.get("chat_model", chat_models[0]))
    )
    st.session_state.cfg["chat_model"] = selected_chat_model

    # OCR Model Selection
    ocr_models = ["Qwen/Qwen2-VL-72B-Instruct"]
    selected_ocr_model = st.selectbox(
        "OCR (Vision) Model",
        ocr_models,
        index=ocr_models.index(st.session_state.cfg.get("ocr_model", ocr_models[0]))
    )
    st.session_state.cfg["ocr_model"] = selected_ocr_model