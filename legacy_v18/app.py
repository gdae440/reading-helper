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
        "generic_api_key": "",
        "generic_base_url": "https://api.siliconflow.cn/v1" # 新增: 自定义 Base URL
    }

def load_vocab():
    # 尝试从根目录读取，实现数据互通
    VOCAB_FILE = "../my_vocab.json" 
    if not os.path.exists(VOCAB_FILE):
        VOCAB_FILE = "my_vocab.json" # 回退到当前目录
        
    if os.path.exists(VOCAB_FILE):
        try: return json.load(open(VOCAB_FILE, "r", encoding="utf-8"))
        except: return []
    return []

def save_vocab(vocab_list):
    # 尝试保存到根目录
    VOCAB_FILE = "../my_vocab.json"
    try:
        # 简单的路径检查，如果上级目录不可写则写当前目录
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
    # 修复 regex 转义
    safe_name = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', snippet)
    safe_name = re.sub(r'[\s]+', '_', safe_name).strip()
    if not safe_name: return f"read_aloud_{datetime.now().strftime('%H%M%S')}.mp3"
    return f"{safe_name}.mp3"

# ================= 2. 状态管理 =================

st.set_page_config(page_title="跟读助手 Pro (Legacy)", layout="wide", page_icon="🦋")

if 'cfg' not in st.session_state:
    init_cfg = load_config()
    # 尝试加载环境变量
    env_key = os.getenv("SILICON_KEY")
    if env_key: init_cfg["api_key"] = env_key
    st.session_state.cfg = init_cfg

if 'vocab' not in st.session_state: st.session_state.vocab = load_vocab()
if 'main_text' not in st.session_state: st.session_state.main_text = ""
if 'trans_text' not in st.session_state: st.session_state.trans_text = "" # 新增: 翻译文本状态
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'last_lookup' not in st.session_state: st.session_state.last_lookup = None
if 'temp_audio' not in st.session_state: st.session_state.temp_audio = {}

# ================= 3. 核心逻辑 (API & TTS) =================

# 修复: 支持自定义 Base URL 和 Key
def get_api_client(cfg):
    # 优先使用 "其他 API Key"，如果没有则使用 "SiliconFlow Key"
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
            # 图片压缩逻辑
            buffered = io.BytesIO()
            content.save(buffered, format="JPEG", quality=85)
            b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            res = client.chat.completions.create(model=ocr_model, messages=[{"role": "user", "content": [{"type": "text", "text": "OCR text only. Keep formatting."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}])
            return res.choices[0].message.content, None
            
        elif type == "lookup":
            # 查词 Prompt (使用双引号三连，避免冲突)
            prompt = """Dictionary API. User input: "{content}". Return JSON: {{ "detected_lang": "...", "ipa": "...", "zh": "...", "ru": "..." }} (Concise)"""
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            return json.loads(res.choices[0].message.content), None
            
        elif type == "trans":
            # 新增: 翻译 Prompt
            res = client.chat.completions.create(model=chat_model, messages=[{"role": "user", "content": f"Translate the following text to Chinese (keep it natural):\\n\\n{content}"}])
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

# CSS 样式 (使用双引号三连)
st.markdown("""
<style>
    .stButton > button { width: 100%; border-radius: 8px; }
    div[data-testid="stVerticalBlock"] > div > button[kind="primary"] {
        background: linear-gradient(180deg, #007AFF 0%, #0062cc 100%); color: white; border: none;
    }
    /* 查词卡片样式 */
    div.lookup-card {
        border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px;
        background-color: #f9f9f9; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
        div.lookup-card { background-color: #262730; border-color: #464b5d; }
    }
</style>
""", unsafe_allow_html=True)

# 侧边栏导航
with st.sidebar:
    st.title("🦋 跟读助手")
    selected = option_menu(None, ["学习主页", "单词本", "设置"], 
        icons=['house', 'book', 'gear'], menu_icon="cast", default_index=0)

# --- 页面 1: 设置 ---
if selected == "设置":
    st.header("⚙️ 全局设置")
    
    with st.expander("🔑 API 配置 (必填其一)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.cfg["api_key"] = st.text_input("SiliconFlow Key", value=st.session_state.cfg["api_key"], type="password")
        with c2:
            # 修复: 增加 Base URL 配置，真正支持其他 API
            st.session_state.cfg["generic_api_key"] = st.text_input("其他/备用 Key", value=st.session_state.cfg["generic_api_key"], type="password")
            st.session_state.cfg["generic_base_url"] = st.text_input("Base URL", value=st.session_state.cfg.get("generic_base_url", "https://api.siliconflow.cn/v1"))
            st.caption("如果填了备用 Key，将优先使用备用 Key 和 Base URL。")

    st.subheader("🤖 模型配置")
    c3, c4 = st.columns(2)
    with c3: st.session_state.cfg["chat_model"] = st.text_input("Chat 模型", value=st.session_state.cfg["chat_model"])
    with c4: st.session_state.cfg["ocr_model"] = st.text_input("OCR 模型", value=st.session_state.cfg["ocr_model"])

    st.subheader("🔊 语音配置")
    lang_opts = ["🇬🇧 英语", "🇫🇷 法语", "🇩🇪 德语", "🇷🇺 俄语"]
    st.session_state.cfg["learn_lang"] = st.selectbox("学习目标语言", lang_opts, index=lang_opts.index(st.session_state.cfg["learn_lang"]))
    st.session_state.cfg["engine"] = st.selectbox("语音引擎", ["Edge (推荐)", "SiliconFlow", "Google"], index=["Edge (推荐)", "SiliconFlow", "Google"].index(st.session_state.cfg["engine"]))
    st.session_state.cfg["speed"] = st.slider("语速", -50, 50, st.session_state.cfg["speed"], step=10)

# --- 页面 2: 学习主页 ---
elif selected == "学习主页":
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        # 文本输入区
        mode = st.radio("输入模式", ["文本粘贴", "拍照识别 (OCR)"], horizontal=True, label_visibility="collapsed")
        
        if mode == "文本粘贴":
            txt_input = st.text_area("输入文本", height=150, label_visibility="collapsed", placeholder="在此输入外语文本...")
            if st.button("确认文本", use_container_width=True):
                st.session_state.main_text = txt_input
                st.session_state.trans_text = "" # 清空旧翻译
                st.rerun()
        else:
            up = st.file_uploader("上传图片", type=['jpg','png'])
            if up and st.button("开始识别"):
                with st.spinner("正在识别..."):
                    res, err = api_call("ocr", Image.open(up), st.session_state.cfg)
                    if res: 
                        st.session_state.main_text = res
                        st.session_state.trans_text = ""
                        st.rerun()
                    else: st.error(err)

        # 阅读器区域
        if st.session_state.main_text:
            st.divider()
            st.markdown("### 📖 阅读区")
            st.info(st.session_state.main_text)
            
            # 翻译显示区
            if st.session_state.trans_text:
                st.success(f"**译文：**\\n{st.session_state.trans_text}")

            # 功能按钮栏
            b1, b2 = st.columns(2)
            with b1:
                if st.button("▶️ 朗读全文", type="primary", use_container_width=True):
                    with st.spinner("生成语音中..."):
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
            
            with b2:
                # 🔥 修复: 新增一键翻译功能
                if st.button("📝 全文翻译", use_container_width=True):
                    with st.spinner("正在翻译..."):
                        trans, err = api_call("trans", st.session_state.main_text, st.session_state.cfg)
                        if trans:
                            st.session_state.trans_text = trans
                            st.rerun()
                        else: st.error(err)

            # 音频播放器
            if st.session_state.audio_data:
                st.audio(st.session_state.audio_data, format='audio/mpeg')
                fname = get_smart_filename(st.session_state.main_text)
                st.download_button("⬇️ 下载音频", st.session_state.audio_data, file_name=fname)

    with col_r:
        st.markdown("### 🔍 快速查词")
        q_w = st.text_input("输入单词", key="lookup_input")
        
        # 🔥 修复: 查词显示问题
        if st.button("查询", use_container_width=True) and q_w:
            with st.spinner("查询中..."):
                info, err = api_call("lookup", q_w, st.session_state.cfg)
                if info:
                    # 保存到 Session 状态
                    info["word"] = q_w
                    st.session_state.last_lookup = info
                    
                    # 自动保存到生词本 (去重)
                    exists = any(i['word'] == q_w for i in st.session_state.vocab)
                    if not exists:
                        st.session_state.vocab.insert(0, {"word": q_w, "lang": st.session_state.cfg["learn_lang"], "date": datetime.now().strftime("%Y-%m-%d"), **info})
                        save_vocab(st.session_state.vocab)
                    
                    st.rerun() # 强制刷新显示结果
                else:
                    st.error(err)

        # 显示查词结果 (从 Session 读取，保证刷新后还在)
        if st.session_state.last_lookup:
            ll = st.session_state.last_lookup
            st.markdown(f"""
            <div class="lookup-card">
                <h3>{ll['word']}</h3>
                <p style="color:#666">[{ll.get('ipa','--')}]</p>
                <hr>
                <p><b>🇨🇳 中文：</b> {ll.get('zh','--')}</p>
                <p><b>🇷🇺 俄语：</b> {ll.get('ru','--')}</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🔊 单词发音", use_container_width=True):
                ab, _ = asyncio.run(get_audio_bytes_mixed(ll['word'], "Edge (推荐)", "en-US-AriaNeural", 0, st.session_state.cfg))
                if ab: st.audio(ab, format="audio/mpeg", autoplay=True)

# --- 页面 3: 单词本 ---
elif selected == "单词本":
    st.markdown(f"### 📚 生词本 ({len(st.session_state.vocab)})")
    if not st.session_state.vocab:
        st.info("暂无生词，快去阅读页添加吧！")
    else:
        for i, item in enumerate(st.session_state.vocab):
            with st.expander(f"{item['word']}  [{item.get('ipa','')}]"):
                st.write(f"**释义：** {item.get('zh','')} / {item.get('ru','')}")
                if st.button("删除", key=f"del_{i}"):
                    st.session_state.vocab.pop(i)
                    save_vocab(st.session_state.vocab)
                    st.rerun()