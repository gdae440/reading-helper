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
        "engine": "Edge (推荐)",
        "voice_role": "en-GB-RyanNeural",
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
# 新增：专门用于查词发音的状态，防止刷新丢失
if 'lookup_audio' not in st.session_state: st.session_state.lookup_audio = None 

# ================= 3. 核心逻辑 =================

def get_api_client(cfg):
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
            lang_map = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru"}
            lang_code = lang_map.get(cfg["learn_lang"], "en")
            tts = gTTS(text=text, lang=lang_code)
            mp3_fp = io.BytesIO(); tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e: return None, f"Google Error: {e}"
    return None, "Unknown Engine"

# ================= 4. UI 渲染 =================

# CSS 升级：更干净的边框，移除复杂的装饰，增加间距
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
    h1, h2, h3 { font-weight: 600; }
    .small-font { font-size: 12px; color: #666; }
</style>
""", unsafe_allow_html=True)

# --- 侧边栏：导航 + 语音控制 ---
with st.sidebar:
    st.markdown("### 跟读助手 Pro")
    selected = option_menu(None, ["学习主页", "单词本", "设置"], 
        icons=['book', 'bookmark', 'sliders'], menu_icon="cast", default_index=0,
        styles={"nav-link": {"font-size": "14px", "text-align": "left", "margin":"0px"}})
    
    st.divider()
    
    # 语音配置直接放侧边栏，方便随时调
    st.markdown("#### 🔊 语音控制")
    
    lang_opts = ["🇬🇧 英语", "🇫🇷 法语", "🇩🇪 德语", "🇷🇺 俄语"]
    # 保持之前选中的语言
    curr_lang_idx = 0
    if st.session_state.cfg["learn_lang"] in lang_opts:
        curr_lang_idx = lang_opts.index(st.session_state.cfg["learn_lang"])
    
    new_lang = st.selectbox("目标语言", lang_opts, index=curr_lang_idx)
    if new_lang != st.session_state.cfg["learn_lang"]:
        st.session_state.cfg["learn_lang"] = new_lang
        # 语言变了，重置一下发音人
        if "英语" in new_lang: st.session_state.cfg["voice_role"] = "en-GB-RyanNeural"
        elif "法语" in new_lang: st.session_state.cfg["voice_role"] = "fr-FR-HenriNeural"
        elif "德语" in new_lang: st.session_state.cfg["voice_role"] = "de-DE-ConradNeural"
        elif "俄语" in new_lang: st.session_state.cfg["voice_role"] = "ru-RU-DmitryNeural"
        st.rerun()

    eng_opts = ["Edge (推荐)", "SiliconFlow", "Google"]
    curr_eng_idx = 0
    if st.session_state.cfg["engine"] in eng_opts:
        curr_eng_idx = eng_opts.index(st.session_state.cfg["engine"])
    st.session_state.cfg["engine"] = st.selectbox("语音引擎", eng_opts, index=curr_eng_idx)
    
    # 根据引擎显示不同的音色选项
    if "Edge" in st.session_state.cfg["engine"]:
        # 简单的音色映射
        voice_map = {
            "🇬🇧 英语": {"Ryan (英/男)": "en-GB-RyanNeural", "Aria (美/女)": "en-US-AriaNeural"},
            "🇫🇷 法语": {"Henri (法/男)": "fr-FR-HenriNeural", "Denise (法/女)": "fr-FR-DeniseNeural"},
            "🇩🇪 德语": {"Conrad (德/男)": "de-DE-ConradNeural", "Katja (德/女)": "de-DE-KatjaNeural"},
            "🇷🇺 俄语": {"Dmitry (俄/男)": "ru-RU-DmitryNeural", "Svetlana (俄/女)": "ru-RU-SvetlanaNeural"},
        }
        current_voices = voice_map.get(st.session_state.cfg["learn_lang"], {})
        voice_names = list(current_voices.keys())
        if voice_names:
            # 尝试找到当前音色对应的名字
            curr_v_name = voice_names[0]
            for name, code in current_voices.items():
                if code == st.session_state.cfg["voice_role"]:
                    curr_v_name = name
                    break
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
            if code == st.session_state.cfg["voice_role"]:
                curr_sf = name
        sel_sf = st.selectbox("选择音色", sf_names, index=sf_names.index(curr_sf) if curr_sf in sf_names else 0)
        st.session_state.cfg["voice_role"] = sf_voices[sel_sf]

    st.session_state.cfg["speed"] = st.slider("语速调节", -50, 50, st.session_state.cfg["speed"], step=10)


# --- 主界面逻辑 ---

if selected == "设置":
    st.subheader("全局设置")
    
    # 使用 tabs 整理布局
    tab1, tab2 = st.tabs(["🔑 API 配置", "🤖 模型参数"])
    
    with tab1:
        st.info("推荐优先使用备用 API，支持自定义 OpenAI 格式接口。")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.cfg["generic_base_url"] = st.text_input("API Base URL", value=st.session_state.cfg.get("generic_base_url", "https://api.siliconflow.cn/v1"))
        with c2:
            st.session_state.cfg["generic_api_key"] = st.text_input("API Key", value=st.session_state.cfg.get("generic_api_key", ""), type="password")
            
        with st.expander("旧版 SiliconFlow 原生配置 (可选)"):
            st.session_state.cfg["api_key"] = st.text_input("SiliconFlow Key", value=st.session_state.cfg["api_key"], type="password")

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

            # 操作栏
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
        # 使用 form 避免每次输入字符都刷新
        with st.form("lookup_form"):
            q_w = st.text_input("单词", placeholder="输入单词...")
            submitted = st.form_submit_button("查询", use_container_width=True)
            
        if submitted and q_w:
            with st.spinner("查询中..."):
                info, err = api_call("lookup", q_w, st.session_state.cfg)
                if info:
                    info["word"] = q_w
                    st.session_state.last_lookup = info
                    st.session_state.lookup_audio = None # 重置发音
                    
                    # 自动保存
                    exists = any(i['word'] == q_w for i in st.session_state.vocab)
                    if not exists:
                        st.session_state.vocab.insert(0, {"word": q_w, "lang": st.session_state.cfg["learn_lang"], "date": datetime.now().strftime("%Y-%m-%d"), **info})
                        save_vocab(st.session_state.vocab)
                    st.rerun()
                else:
                    st.error(err)

        if st.session_state.last_lookup:
            ll = st.session_state.last_lookup
            # 简洁的卡片展示
            st.markdown(f"""
            <div class="lookup-card">
                <h3 style="margin:0">{ll['word']}</h3>
                <div style="color:#666; margin-bottom:10px; font-family:monospace;">[{ll.get('ipa','--')}]</div>
                <div style="margin-bottom:5px"><b>🇨🇳</b> {ll.get('zh','--')}</div>
                <div><b>🇷🇺</b> {ll.get('ru','--')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            # 发音按钮
            if st.button("🔊 朗读单词", use_container_width=True):
                ab, _ = asyncio.run(get_audio_bytes_mixed(ll['word'], "Edge (推荐)", "en-US-AriaNeural", 0, st.session_state.cfg))
                if ab:
                    st.session_state.lookup_audio = ab
                    st.rerun() # 关键：刷新以显示音频播放器
            
            # 稳定的音频播放器
            if st.session_state.lookup_audio:
                st.audio(st.session_state.lookup_audio, format="audio/mpeg", autoplay=True)

elif selected == "单词本":
    st.subheader(f"我的生词本 ({len(st.session_state.vocab)})")
    if not st.session_state.vocab:
        st.info("空空如也。在右侧查词自动添加。")
    else:
        for i, item in enumerate(st.session_state.vocab):
            with st.expander(f"{item['word']}", expanded=False):
                st.write(f"[{item.get('ipa','')}]")
                st.write(f"🇨🇳 {item.get('zh','')}")
                st.write(f"🇷🇺 {item.get('ru','')}")
                c_del, c_play = st.columns([1, 4])
                with c_del:
                    if st.button("🗑️ 删除", key=f"d_{i}"):
                        st.session_state.vocab.pop(i)
                        save_vocab(st.session_state.vocab)
                        st.rerun()