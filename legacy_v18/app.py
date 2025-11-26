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

# ================= 1. 核心配置 =================

def load_config():
    return {
        "api_key": "",
        "engine": "Google", # 默认改为 Google
        "voice_role": "en",
        "speed": 0,
        "learn_lang": "🇬🇧 英语",
        "chat_model": "deepseek-ai/DeepSeek-V3",
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "generic_api_key": "",
        "generic_base_url": "https://api.siliconflow.cn/v1"
    }

def load_vocab():
    VOCAB_FILE = "../my_vocab.json" 
    if not os.path.exists(VOCAB_FILE):
        VOCAB_FILE = "my_vocab.json"
    if os.path.exists(VOCAB_FILE):
        try: return json.load(open(VOCAB_FILE, "r", encoding="utf-8"))
        except: return []
    return []

def save_vocab(vocab_list):
    VOCAB_FILE = "../my_vocab.json"
    try:
        with open(VOCAB_FILE, "w", encoding="utf-8") as f:
            json.dump(vocab_list, f, ensure_ascii=False, indent=2)
    except:
        try:
            with open("my_vocab.json", "w", encoding="utf-8") as f:
                json.dump(vocab_list, f, ensure_ascii=False, indent=2)
        except: pass

def get_smart_filename(text):
    if not text: return f"read_aloud_{datetime.now().strftime('%H%M%S')}.mp3"
    snippet = text[:50]
    safe_name = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', snippet)
    safe_name = re.sub(r'[\s]+', '_', safe_name).strip()
    if not safe_name: return f"read_aloud_{datetime.now().strftime('%H%M%S')}.mp3"
    return f"{safe_name}.mp3"

# ================= 2. 状态管理 =================

st.set_page_config(page_title="跟读助手 Pro", layout="wide", page_icon="📘")

if 'cfg' not in st.session_state:
    init_cfg = load_config()
    env_key = os.getenv("SILICON_KEY")
    if env_key: init_cfg["api_key"] = env_key
    st.session_state.cfg = init_cfg

if 'vocab' not in st.session_state: st.session_state.vocab = load_vocab()
if 'main_text' not in st.session_state: st.session_state.main_text = ""
if 'trans_text' not in st.session_state: st.session_state.trans_text = ""
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'last_lookup' not in st.session_state: st.session_state.last_lookup = None
if 'lookup_audio' not in st.session_state: st.session_state.lookup_audio = None 
# 专门用于生词本播放的缓存 { "word": bytes }
if 'vocab_audio_cache' not in st.session_state: st.session_state.vocab_audio_cache = {}

# ================= 3. 核心逻辑 =================

def get_api_client(cfg):
    # 这里的逻辑是：如果有 generic_api_key 就用它，否则用 silicon key
    key = cfg.get("generic_api_key") if cfg.get("generic_api_key") else cfg.get("api_key")
    base_url = cfg.get("generic_base_url") if cfg.get("generic_base_url") else "https://api.siliconflow.cn/v1"
    if not key: return None, "未配置 API Key"
    return OpenAI(api_key=key, base_url=base_url), None

def api_call(type, content, cfg):
    client, err = get_api_client(cfg)
    if not client: return None, err

    chat_model = cfg.get("chat_model", "deepseek-ai/DeepSeek-V3")
    ocr_model = cfg.get("ocr_model", "Qwen/Qwen2.5-VL-72B-Instruct")

    try:
        if type == "ocr":
            buffered = io.BytesIO()
            content.save(buffered, format="JPEG", quality=85)
            b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            res = client.chat.completions.create(model=ocr_model, messages=[{"role": "user", "content": [{"type": "text", "text": "OCR text only. Keep formatting."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}])
            return res.choices[0].message.content, None
        elif type == "lookup":
            prompt = """Dictionary API. User input: "{content}". Return JSON: {{ "detected_lang": "...", "ipa": "...", "zh": "...", "ru": "..." }} (Concise)"""
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            return json.loads(res.choices[0].message.content), None
        elif type == "trans":
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": f"Translate to Chinese (Natural & Concise):\\n\\n{content}"}])
            return res.choices[0].message.content, None
    except Exception as e:
        return None, f"API Error: {str(e)}"
    return None, "Unknown Error"

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, cfg):
    if "Edge" in engine_type:
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=f"{speed_int:+d}%")
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Edge Error: {e}"
    elif "SiliconFlow" in engine_type:
        client, err = get_api_client(cfg)
        if not client: return None, err
        model_id = voice_id.split(":")[0] if ":" in voice_id else "FunAudioLLM/CosyVoice2-0.5B"
        try:
            sf_speed = 1.0 + (speed_int / 100.0)
            response = client.audio.speech.create(model=model_id, voice=voice_id, input=text, speed=sf_speed)
            return response.content, None
        except Exception as e: return None, f"SF Error: {e}"
    elif "Google" in engine_type:
        try:
            # Google TTS 语言代码映射
            lang_map = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru"}
            lang_code = lang_map.get(cfg["learn_lang"], "en")
            # 简单的逻辑：如果 voice_id 看起来像语言代码，就用它
            if len(voice_id) == 2: lang_code = voice_id
            
            tts = gTTS(text=text, lang=lang_code)
            mp3_fp = io.BytesIO(); tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Google Error: {e}"
    return None, "Unknown Engine"

# ================= 4. Anki 导出逻辑 =================
async def create_anki_package_streamlit(selected_items, cfg):
    deck = genanki.Deck(random.randrange(1<<30, 1<<31), '跟读助手生词本')
    model = genanki.Model(random.randrange(1<<30, 1<<31), 'Simple Model', 
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{'name': 'Card 1', 'qfmt': '{{Question}}<br>{{Audio}}', 'afmt': '{{FrontSide}}<hr id="answer">{{Answer}}'}])
    
    media_files = []
    temp_files = []
    
    # 进度条
    progress_bar = st.progress(0, text="正在生成 Anki 包...")
    
    for i, item in enumerate(selected_items):
        progress_bar.progress((i + 1) / len(selected_items), text=f"处理单词: {item['word']}")
        # 默认用 Edge 生成发音，比较快
        # 根据 item 的语言猜测发音人，或者默认用英语
        v_role = "en-US-AriaNeural" 
        # 简单的语言检测
        if "ru" in str(item) or "俄" in str(item): v_role = "ru-RU-DmitryNeural"
        elif "fr" in str(item) or "法" in str(item): v_role = "fr-FR-HenriNeural"
        
        aud, _ = await get_audio_bytes_mixed(item['word'], "Edge (推荐)", v_role, 0, cfg)
        
        fname = ""
        if aud:
            fname = f"anki_{random.randint(1000,9999)}_{i}.mp3"
            with open(fname, "wb") as f: f.write(aud)
            media_files.append(fname)
            temp_files.append(fname)
        
        deck.add_note(genanki.Note(model=model, fields=[
            f"{item['word']} <br> <small style='color:grey'>{item.get('ipa','')}</small>",
            f"🇨🇳 {item.get('zh','')}<br>🇷🇺 {item.get('ru','')}",
            f"[sound:{fname}]" if fname else ""
        ]))
    
    pkg = genanki.Package(deck); pkg.media_files = media_files
    
    out_io = io.BytesIO()
    pkg.write_to_file(out_io)
    
    # 清理
    for f in temp_files:
        if os.path.exists(f): os.remove(f)
    
    progress_bar.empty()
    out_io.seek(0)
    return out_io

# ================= 5. UI 渲染 =================

st.markdown("""
<style>
    .stButton > button { width: 100%; border-radius: 6px; height: 2.5rem; }
    div[data-testid="stVerticalBlock"] > div > button[kind="primary"] {
        background-color: #007AFF; color: white; border: none;
    }
    div.lookup-card {
        border: 1px solid #e5e5e5; border-radius: 8px; padding: 20px;
        background-color: white; margin-bottom: 15px;
    }
    @media (prefers-color-scheme: dark) {
        div.lookup-card { background-color: #1e1e1e; border-color: #333; }
    }
</style>
""", unsafe_allow_html=True)

# --- 侧边栏：导航 + 语音控制 ---
with st.sidebar:
    st.markdown("### 跟读助手 Pro")
    selected = option_menu(None, ["学习主页", "单词本", "设置"], 
        icons=['book', 'bookmark', 'sliders'], menu_icon="cast", default_index=0,
        styles={"nav-link": {"font-size": "14px", "text-align": "left", "margin":"0px"}})
    
    st.divider()
    st.markdown("#### 🔊 语音控制")
    
    lang_opts = ["🇬🇧 英语", "🇫🇷 法语", "🇩🇪 德语", "🇷🇺 俄语"]
    curr_lang_idx = 0
    if st.session_state.cfg["learn_lang"] in lang_opts:
        curr_lang_idx = lang_opts.index(st.session_state.cfg["learn_lang"])
    
    new_lang = st.selectbox("目标语言", lang_opts, index=curr_lang_idx)
    if new_lang != st.session_state.cfg["learn_lang"]:
        st.session_state.cfg["learn_lang"] = new_lang
        if "英语" in new_lang: st.session_state.cfg["voice_role"] = "en-GB-RyanNeural"
        elif "法语" in new_lang: st.session_state.cfg["voice_role"] = "fr-FR-HenriNeural"
        elif "德语" in new_lang: st.session_state.cfg["voice_role"] = "de-DE-ConradNeural"
        elif "俄语" in new_lang: st.session_state.cfg["voice_role"] = "ru-RU-DmitryNeural"
        st.rerun()

    # 修复：调整引擎顺序 Google -> Edge -> SiliconFlow
    eng_opts = ["Google", "Edge (推荐)", "SiliconFlow"]
    curr_eng_idx = 0
    if st.session_state.cfg["engine"] in eng_opts:
        curr_eng_idx = eng_opts.index(st.session_state.cfg["engine"])
    st.session_state.cfg["engine"] = st.selectbox("语音引擎", eng_opts, index=curr_eng_idx)
    
    if "Edge" in st.session_state.cfg["engine"]:
        voice_map = {
            "🇬🇧 英语": {"Ryan (英/男)": "en-GB-RyanNeural", "Aria (美/女)": "en-US-AriaNeural"},
            "🇫🇷 法语": {"Henri (法/男)": "fr-FR-HenriNeural", "Denise (法/女)": "fr-FR-DeniseNeural"},
            "🇩🇪 德语": {"Conrad (德/男)": "de-DE-ConradNeural", "Katja (德/女)": "de-DE-KatjaNeural"},
            "🇷🇺 俄语": {"Dmitry (俄/男)": "ru-RU-DmitryNeural", "Svetlana (俄/女)": "ru-RU-SvetlanaNeural"},
        }
        current_voices = voice_map.get(st.session_state.cfg["learn_lang"], {})
        voice_names = list(current_voices.keys())
        if voice_names:
            curr_v_name = voice_names[0]
            for name, code in current_voices.items():
                if code == st.session_state.cfg["voice_role"]: curr_v_name = name; break
            selected_v_name = st.selectbox("选择音色", voice_names, index=voice_names.index(curr_v_name) if curr_v_name in voice_names else 0)
            st.session_state.cfg["voice_role"] = current_voices[selected_v_name]
            
    elif "SiliconFlow" in st.session_state.cfg["engine"]:
        sf_voices = {
            "Benjamin (英/男)": "FunAudioLLM/CosyVoice2-0.5B:benjamin",
            "Alex (美/男)": "FunAudioLLM/CosyVoice2-0.5B:alex",
            "Bella (美/女)": "FunAudioLLM/CosyVoice2-0.5B:bella"
        }
        sf_names = list(sf_voices.keys())
        curr_sf = sf_names[0]
        for name, code in sf_voices.items():
            if code == st.session_state.cfg["voice_role"]: curr_sf = name
        sel_sf = st.selectbox("选择音色", sf_names, index=sf_names.index(curr_sf) if curr_sf in sf_names else 0)
        st.session_state.cfg["voice_role"] = sf_voices[sel_sf]
    
    elif "Google" in st.session_state.cfg["engine"]:
        st.session_state.cfg["voice_role"] = "en" # 默认占位，实际由 api_call 内部分配

    st.session_state.cfg["speed"] = st.slider("语速调节", -50, 50, st.session_state.cfg["speed"], step=10)


# --- 主界面逻辑 ---

if selected == "设置":
    st.subheader("全局设置")
    
    tab1, tab2 = st.tabs(["🔑 API 配置", "🤖 模型参数"])
    
    with tab1:
        # 修复：调整顺序，SiliconFlow 在上，其他 API 在下
        st.session_state.cfg["api_key"] = st.text_input("SiliconFlow Key (用于 AI 语音)", value=st.session_state.cfg["api_key"], type="password")
        st.caption("推荐使用 SiliconFlow Key 以获得最佳体验。")
        
        st.divider()
        st.markdown("##### 其他/备用 API (可选)")
        st.info("如果填写了这里，查词和 OCR 将优先使用此配置。")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.cfg["generic_base_url"] = st.text_input("Base URL", value=st.session_state.cfg.get("generic_base_url", "https://api.siliconflow.cn/v1"))
        with c2:
            st.session_state.cfg["generic_api_key"] = st.text_input("API Key", value=st.session_state.cfg.get("generic_api_key", ""), type="password")

    with tab2:
        c3, c4 = st.columns(2)
        with c3: st.session_state.cfg["chat_model"] = st.text_input("Chat 模型名称", value=st.session_state.cfg["chat_model"])
        with c4: st.session_state.cfg["ocr_model"] = st.text_input("OCR 模型名称", value=st.session_state.cfg["ocr_model"])

elif selected == "学习主页":
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        st.caption("阅读与朗读")
        mode = st.radio("输入模式", ["文本", "OCR 拍照"], horizontal=True, label_visibility="collapsed")
        
        if mode == "文本":
            txt_input = st.text_area("内容输入", height=200, label_visibility="collapsed", placeholder="在此输入或粘贴文本...")
            if st.button("确认内容", use_container_width=True):
                st.session_state.main_text = txt_input
                st.session_state.trans_text = ""
                st.rerun()
        else:
            up = st.file_uploader("上传图片", type=['jpg','png'], label_visibility="collapsed")
            if up and st.button("开始识别", use_container_width=True):
                with st.spinner("AI 识别中..."):
                    res, err = api_call("ocr", Image.open(up), st.session_state.cfg)
                    if res: 
                        st.session_state.main_text = res
                        st.session_state.trans_text = ""
                        st.rerun()
                    else: st.error(err)

        if st.session_state.main_text:
            st.markdown("---")
            st.markdown(f"**原文内容：**\n\n{st.session_state.main_text}")
            
            if st.session_state.trans_text:
                st.info(f"**译文：**\n\n{st.session_state.trans_text}")

            c_act1, c_act2 = st.columns(2)
            with c_act1:
                if st.button("▶️ 朗读全文", type="primary", use_container_width=True):
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
                            st.rerun()
                        else: st.error(err)
            with c_act2:
                if st.button("📝 全文翻译", use_container_width=True):
                    with st.spinner("翻译中..."):
                        trans, err = api_call("trans", st.session_state.main_text, st.session_state.cfg)
                        if trans:
                            st.session_state.trans_text = trans
                            st.rerun()
                        else: st.error(err)

            if st.session_state.audio_data:
                st.audio(st.session_state.audio_data, format='audio/mpeg')

    with col_r:
        st.caption("智能查词")
        with st.form("lookup_form"):
            q_w = st.text_input("单词", placeholder="输入单词...")
            submitted = st.form_submit_button("查询", use_container_width=True)
            
        if submitted and q_w:
            with st.spinner("查询中..."):
                info, err = api_call("lookup", q_w, st.session_state.cfg)
                if info:
                    info["word"] = q_w
                    st.session_state.last_lookup = info
                    st.session_state.lookup_audio = None
                    exists = any(i['word'] == q_w for i in st.session_state.vocab)
                    if not exists:
                        st.session_state.vocab.insert(0, {"word": q_w, "lang": st.session_state.cfg["learn_lang"], "date": datetime.now().strftime("%Y-%m-%d"), **info})
                        save_vocab(st.session_state.vocab)
                    st.rerun()
                else:
                    st.error(err)

        if st.session_state.last_lookup:
            ll = st.session_state.last_lookup
            st.markdown(f"""
            <div class="lookup-card">
                <h3 style="margin:0">{ll['word']}</h3>
                <div style="color:#666; margin-bottom:10px; font-family:monospace;">[{ll.get('ipa','--')}]</div>
                <div style="margin-bottom:5px"><b>🇨🇳</b> {ll.get('zh','--')}</div>
                <div><b>🇷🇺</b> {ll.get('ru','--')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🔊 朗读单词", use_container_width=True):
                ab, _ = asyncio.run(get_audio_bytes_mixed(ll['word'], "Edge (推荐)", "en-US-AriaNeural", 0, st.session_state.cfg))
                if ab:
                    st.session_state.lookup_audio = ab
                    st.rerun()
            
            if st.session_state.lookup_audio:
                st.audio(st.session_state.lookup_audio, format="audio/mpeg", autoplay=True)

elif selected == "单词本":
    # 修复: 添加 Anki 导出功能 + 多选框
    st.subheader(f"我的生词本 ({len(st.session_state.vocab)})")
    
    if not st.session_state.vocab:
        st.info("空空如也。在右侧查词自动添加。")
    else:
        # 全选/操作栏
        col_sel, col_exp = st.columns([3, 1])
        with col_exp:
            if st.button("📦 导出 Anki 包"):
                # 找出所有选中的
                # 注意：Streamlit 的 checkbox 在循环中需要 unique key
                # 这里我们先扫描一遍状态
                selected_items = []
                for i, item in enumerate(st.session_state.vocab):
                    if st.session_state.get(f"chk_{i}", False):
                        selected_items.append(item)
                
                if not selected_items:
                    st.warning("请先勾选单词！")
                else:
                    ankibytes = asyncio.run(create_anki_package_streamlit(selected_items, st.session_state.cfg))
                    st.download_button(
                        label="⬇️ 点击下载 .apkg",
                        data=ankibytes,
                        file_name="anki_export.apkg",
                        mime="application/octet-stream"
                    )

        st.divider()
        
        # 单词列表循环
        for i, item in enumerate(st.session_state.vocab):
            c_chk, c_word, c_act = st.columns([0.5, 3, 1])
            with c_chk:
                st.checkbox("", key=f"chk_{i}")
            
            with c_word:
                with st.expander(f"**{item['word']}** [{item.get('ipa','')}]"):
                    st.write(f"🇨🇳 {item.get('zh','')}")
                    st.write(f"🇷🇺 {item.get('ru','')}")
            
            with c_act:
                # 修复: 播放按钮逻辑
                if st.button("🔊", key=f"play_{i}"):
                    # 使用 Edge 播放，根据内容大概猜一下语言
                    v_role = "en-US-AriaNeural"
                    if "ru" in str(item) or "俄" in str(item): v_role = "ru-RU-DmitryNeural"
                    elif "fr" in str(item) or "法" in str(item): v_role = "fr-FR-HenriNeural"
                    
                    ab, _ = asyncio.run(get_audio_bytes_mixed(item['word'], "Edge (推荐)", v_role, 0, st.session_state.cfg))
                    if ab:
                        st.session_state.vocab_audio_cache[item['word']] = ab
                        st.rerun()
                        
                if st.button("🗑️", key=f"del_{i}"):
                    st.session_state.vocab.pop(i)
                    save_vocab(st.session_state.vocab)
                    st.rerun()
            
            # 检查是否有该单词的缓存音频需要播放
            if item['word'] in st.session_state.vocab_audio_cache:
                st.audio(st.session_state.vocab_audio_cache[item['word']], format="audio/mpeg", autoplay=True)
                # 播放一次后清除，避免刷新一直播? 或者保留? 保留比较好，除非点别的
                # del st.session_state.vocab_audio_cache[item['word']]