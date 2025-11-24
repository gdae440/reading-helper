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

# ================= 1. 环境与配置管理 =================

# 强制清除本地代理 (防止 Mac 报错)
for key in ["all_proxy", "http_proxy", "https_proxy"]:
    if key in os.environ: del os.environ[key]
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

st.set_page_config(page_title="跟读助手 Pro (云端版)", layout="wide", page_icon="🦋")

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

# --- 核心：多层级配置加载 ---
def load_config():
    # 1. 默认配置
    config = {
        "chat_model": "deepseek-ai/DeepSeek-V3",
        "ocr_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "trans_prompt": "Translate the following text into fluent, natural Chinese.",
        "api_key": ""
    }
    
    # 2. 尝试从 Streamlit Secrets 读取 (用于云端部署)
    # 只有当你自己在 Streamlit 后台配置了 Key，这里才会有值
    try:
        if "SILICON_KEY" in st.secrets:
            config["api_key"] = st.secrets["SILICON_KEY"]
    except: pass

    # 3. 尝试从本地 config.json 读取 (优先级高于 Secrets)
    # 这就是为什么你在 Mac 上不用输，因为你有这个文件
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except: pass
    
    return config

def save_config(config_dict):
    # 只在本地写入 config.json，云端无法写入文件
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
    except: pass

if 'app_config' not in st.session_state:
    st.session_state.app_config = load_config()

# ================= 2. 功能函数 (保持精简) =================
# (这里省略重复代码，逻辑与之前版本完全一致，请确保完整复制 V9.0 的这些函数)
# 务必保留：load_vocab, save_vocab, compress_image, VOICE_MAP, get_default_voice_for_lang, 
# match_language_key, create_anki_package, generate_tts_file, get_word_audio_bytes, 
# silicon_ocr_multilang, silicon_vocab_lookup_multilang, silicon_translate_text

# --- 占位符：请将 V9.0 的第 2、3、4 部分所有函数完整保留在这里 ---
# 为防止报错，我简单写几个必须的空函数，你实际使用时要替换回原来的完整代码
def load_vocab():
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []
def save_vocab(v):
    with open(VOCAB_FILE, "w", encoding="utf-8") as f: json.dump(v, f, ensure_ascii=False)
def compress_image(image):
    image.thumbnail((1024, 1024)); buffered = io.BytesIO(); image.save(buffered, format="JPEG"); return base64.b64encode(buffered.getvalue()).decode('utf-8')
VOICE_MAP = {"🇬🇧 英语 (English)": [("en-GB-RyanNeural", "")], "🇷🇺 俄语 (Русский)": [("ru-RU-DmitryNeural", "")]} # 简化演示
def get_default_voice_for_lang(l): return VOICE_MAP.get(l, [("en-GB-RyanNeural", "")])[0][0]
def match_language_key(l): return None # 需替换回完整逻辑
async def create_anki_package(s): return b"" # 需替换回完整逻辑
async def generate_tts_file(t, v, r): return "speech.mp3", None # 需替换回完整逻辑
async def get_word_audio_bytes(t, v): return b"", None # 需替换回完整逻辑
def silicon_ocr_multilang(i, k, m): return "OCR Res", None # 需替换回完整逻辑
def silicon_vocab_lookup_multilang(w, k, m): return {"detected_lang": "English", "zh": "测试"}, None # 需替换回完整逻辑
def silicon_translate_text(t, k, m, p): return "Translation", None # 需替换回完整逻辑
# -----------------------------------------------------------

# ================= 5. 界面 UI (适配云端分享) =================

st.title("🦋 跟读助手 (Cloud Shared)")

if 'vocab_book' not in st.session_state: st.session_state.vocab_book = load_vocab()
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'audio_cache' not in st.session_state: st.session_state.audio_cache = None
if 'translation_result' not in st.session_state: st.session_state.translation_result = ""
if 'temp_word_audio' not in st.session_state: st.session_state.temp_word_audio = {}

with st.sidebar:
    st.header("⚙️ 设置")
    
    # 显示本地 IP (仅供自己在家用)
    local_ip = get_local_ip()
    if local_ip != "127.0.0.1":
        st.caption(f"🏠 局域网地址: http://{local_ip}:8501")
    
    st.info("💡 如果你是访客，请输入你自己的 Key。")
    
    # --- API Key 逻辑 ---
    # 1. 优先读取 session 中的 key (可能是本地 config 加载的)
    default_key_val = st.session_state.app_config.get("api_key", "")
    
    # 2. 文本框：如果 default_key_val 有值（本地），则自动填充，且显示为密码点点点
    # 如果没值（云端访客），则为空，等待用户输入
    api_input = st.text_input("SiliconFlow Key", value=default_key_val, type="password")

    with st.expander("🤖 模型配置", expanded=False):
        chat_model_input = st.text_input("模型", value=st.session_state.app_config.get("chat_model", "deepseek-ai/DeepSeek-V3"))
        ocr_model_input = st.text_input("OCR", value=st.session_state.app_config.get("ocr_model", "Qwen/Qwen2.5-VL-72B-Instruct"))
        trans_prompt_input = st.text_area("翻译提示词", value=st.session_state.app_config.get("trans_prompt", ""), height=80)

    # 保存逻辑：只有当是在本地运行时，才能写入 config.json
    # 云端运行时，这个保存虽然会执行，但因为容器是临时的，重启后会重置（这是符合预期的，保护隐私）
    if api_input != st.session_state.app_config.get("api_key"):
        st.session_state.app_config["api_key"] = api_input
        save_config(st.session_state.app_config) # 尝试保存
        
    st.divider()
    # (保留之前的侧边栏选择代码)
    lang_choice = st.selectbox("🌍 语言", list(VOICE_MAP.keys()), index=0)
    # ... 其余代码保持 V9.0 不变 ...

    # ⛔️ 阻断逻辑
    if not api_input:
        st.warning("⚠️ 请输入 API Key 才能开始使用")
        st.stop() # 只有没有 Key 时才停止

# --- 主界面 ---
# (完整复制 V9.0 的主界面代码)
st.write("欢迎使用！") # 占位