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
from datetime import datetime
from PIL import Image
import genanki
from streamlit_option_menu import option_menu

# ================= 1. 核心配置与工具函数 =================

VOCAB_FILE = "my_vocab.json"

def load_vocab():
    """加载生词本"""
    # 兼容不同运行目录
    paths = ["my_vocab.json", "../my_vocab.json"]
    for p in paths:
        if os.path.exists(p):
            try:
                return json.load(open(p, "r", encoding="utf-8"))
            except:
                pass
    return []

def save_vocab(vocab_list):
    """保存生词本"""
    try:
        with open(VOCAB_FILE, "w", encoding="utf-8") as f:
            json.dump(vocab_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"保存失败: {e}")

def get_smart_filename(text):
    """生成智能文件名"""
    if not text: return f"audio_{datetime.now().strftime('%H%M%S')}.mp3"
    snippet = text[:20]
    safe_name = re.sub(r'[^\w\s\u4e00-\u9fa5-]', '', snippet).strip()
    safe_name = re.sub(r'[\s]+', '_', safe_name)
    return f"{safe_name}.mp3" if safe_name else "audio.mp3"

# ================= 2. 页面初始化与样式 =================

st.set_page_config(page_title="跟读助手 Pro (Legacy)", layout="wide", page_icon="📘")

# Apple Design 风格 CSS
st.markdown("""
<style>
    /* 全局背景与字体 */
    .stApp {
        background-color: #f5f5f7;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    /* 按钮优化 */
    .stButton > button {
        border-radius: 10px;
        border: none;
        font-weight: 500;
        transition: all 0.2s;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* 主按钮蓝色 */
    button[kind="primary"] {
        background-color: #007aff !important;
        color: white !important;
    }
    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e5e5ea;
    }
    /* 查词卡片 */
    div.lookup-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        border: 1px solid #e5e5ea;
    }
</style>
""", unsafe_allow_html=True)

# ================= 3. 状态管理 (Session State) =================

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
if 'last_lookup' not in st.session_state: st.session_state.last_lookup = None
# 音频缓存池，避免重绘丢失
if 'vocab_audio_cache' not in st.session_state: st.session_state.vocab_audio_cache = {}
if 'playing_word_idx' not in st.session_state: st.session_state.playing_word_idx = -1

# ================= 4. 核心 API 逻辑 =================

def get_api_client(cfg):
    """获取 OpenAI 兼容客户端"""
    key = cfg.get("api_key")
    base_url = cfg.get("generic_base_url", "https://api.siliconflow.cn/v1")
    if not key: return None, "❌ 未配置 API Key"
    # 容错处理
    if not base_url.endswith("/v1"): 
        if base_url.endswith("/"): base_url += "v1"
        else: base_url += "/v1"
        
    return OpenAI(api_key=key, base_url=base_url), None

def api_call(task_type, content, cfg):
    """统一 API 调用入口"""
    client, err = get_api_client(cfg)
    if not client: return None, err

    try:
        if task_type == "ocr":
            # 图片转 base64
            buffered = io.BytesIO()
            content.save(buffered, format="JPEG", quality=85)
            b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            res = client.chat.completions.create(
                model=cfg["ocr_model"],
                messages=[{
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": "Recognize all text in this image. Output plain text only."}, 
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]
                }]
            )
            return res.choices[0].message.content, None
            
        elif task_type == "lookup":
            # 强制 JSON 模式
            prompt = f"""Explain the word "{content}" concisely. Return strictly valid JSON format:
            {{ "detected_lang": "en", "ipa": "/.../", "zh": "Chinese definition", "ru": "Russian definition" }}"""
            res = client.chat.completions.create(
                model=cfg["chat_model"],
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(res.choices[0].message.content), None
            
        elif task_type == "trans":
            res = client.chat.completions.create(
                model=cfg["chat_model"],
                messages=[{"role": "user", "content": f"Translate the following text to natural Chinese:\n\n{content}"}]
            )
            return res.choices[0].message.content, None
            
    except Exception as e:
        return None, f"API Error: {str(e)}"
    return None, "Unknown Error"

async def get_audio_bytes_mixed(text, engine_type, voice_id, speed_int, cfg):
    """多引擎 TTS 核心逻辑"""
    if not text: return None, "No text"
    
    # 1. Edge TTS (最强免费)
    if "Edge" in engine_type:
        try:
            # 速度转换: -50 -> -50%, +50 -> +50%
            rate_str = f"{speed_int:+d}%"
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_fp.write(chunk["data"])
            return mp3_fp.getvalue(), None
        except Exception as e:
            return None, f"Edge TTS Error: {e}"

    # 2. SiliconFlow (CosyVoice)
    elif "SiliconFlow" in engine_type:
        client, err = get_api_client(cfg)
        if not client: return None, err
        model_id = "FunAudioLLM/CosyVoice2-0.5B" # 固定默认模型
        # 提取实际 voice 代码 (如果含有 model 前缀则剥离)
        real_voice = voice_id.split(":")[-1] if ":" in voice_id else voice_id 
        
        try:
            # 速度转换: 0 -> 1.0, 10 -> 1.1
            sf_speed = 1.0 + (speed_int / 100.0)
            response = client.audio.speech.create(
                model=model_id,
                voice=model_id + ":" + real_voice, # SF 格式要求
                input=text,
                speed=sf_speed
            )
            return response.content, None
        except Exception as e:
            return None, f"SiliconFlow TTS Error: {e}"

    # 3. Google (gTTS)
    elif "Google" in engine_type:
        try:
            # 语言代码映射
            lang_map = {"🇬🇧 英语": "en", "🇫🇷 法语": "fr", "🇩🇪 德语": "de", "🇷🇺 俄语": "ru"}
            lang_code = lang_map.get(cfg["learn_lang"], "en")
            tts = gTTS(text=text, lang=lang_code)
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            return mp3_fp.getvalue(), None
        except Exception as e:
            return None, f"Google TTS Error: {e}"
            
    return None, "Unknown Engine"

async def create_anki_package(selected_items, cfg):
    """生成 Anki 包"""
    deck = genanki.Deck(random.randrange(1<<30, 1<<31), '跟读助手生词本')
    model = genanki.Model(
        random.randrange(1<<30, 1<<31),
        'Simple Model',
        fields=[{'name': 'Question'}, {'name': 'Answer'}, {'name': 'Audio'}],
        templates=[{
            'name': 'Card 1',
            'qfmt': '<div style="font-size:24px;text-align:center">{{Question}}</div><br>{{Audio}}',
            'afmt': '{{FrontSide}}<hr id="answer"><div style="text-align:center">{{Answer}}</div>',
        }]
    )
    
    media_files = []
    temp_files = [] # 用于后续清理
    
    my_bar = st.progress(0, text="准备生成 Anki 包...")
    
    for idx, item in enumerate(selected_items):
        my_bar.progress((idx + 1) / len(selected_items), text=f"处理: {item['word']}")
        
        # 自动匹配发音角色
        v_role = "en-US-AriaNeural"
        if "ru" in str(item): v_role = "ru-RU-DmitryNeural"
        elif "fr" in str(item): v_role = "fr-FR-HenriNeural"
        
        # 生成音频
        aud_data, _ = await get_audio_bytes_mixed(item['word'], "Edge (推荐)", v_role, 0, cfg)
        
        audio_field = ""
        if aud_data:
            fname = f"anki_{random.randint(1000,9999)}_{idx}.mp3"
            with open(fname, "wb") as f:
                f.write(aud_data)
            media_files.append(fname)
            temp_files.append(fname)
            audio_field = f"[sound:{fname}]"
            
        note = genanki.Note(
            model=model,
            fields=[
                f"{item['word']} <br> <small style='color:grey'>{item.get('ipa','')}</small>",
                f"🇨🇳 {item.get('zh','')}<br>🇷🇺 {item.get('ru','')}",
                audio_field
            ]
        )
        deck.add_note(note)

    pkg = genanki.Package(deck)
    pkg.media_files = media_files
    
    out_io = io.BytesIO()
    pkg.write_to_file(out_io)
    out_io.seek(0)
    
    # 清理临时文件
    for f in temp_files:
        if os.path.exists(f): os.remove(f)
        
    my_bar.empty()
    return out_io

# ================= 5. 侧边栏设置 =================

with st.sidebar:
    st.title("📘 跟读助手 Pro")
    
    # 导航菜单
    selected_page = option_menu(
        menu_title=None,
        options=["学习主页", "单词本", "高级设置"],
        icons=['book', 'journal-bookmark', 'gear'],
        default_index=0,
        styles={"nav-link": {"font-size": "15px", "margin": "5px"}}
    )
    
    st.divider()
    
    # 语音设置卡片
    with st.expander("🔊 语音与语言设置", expanded=True):
        # 语言选择
        lang_options = ["🇬🇧 英语", "🇫🇷 法语", "🇩🇪 德语", "🇷🇺 俄语"]
        current_lang = st.session_state.cfg.get("learn_lang", "🇬🇧 英语")
        # 防止 index out of range
        idx = lang_options.index(current_lang) if current_lang in lang_options else 0
        new_lang = st.selectbox("学习语言", lang_options, index=idx)
        
        if new_lang != current_lang:
            st.session_state.cfg["learn_lang"] = new_lang
            # 切换语言自动重置推荐人
            defaults = {
                "🇬🇧 英语": "en-US-AriaNeural",
                "🇫🇷 法语": "fr-FR-HenriNeural", 
                "🇩🇪 德语": "de-DE-ConradNeural",
                "🇷🇺 俄语": "ru-RU-DmitryNeural"
            }
            st.session_state.cfg["voice_role"] = defaults.get(new_lang, "en-US-AriaNeural")
            st.rerun()

        # 引擎选择
        engine_opts = ["Edge (推荐)", "SiliconFlow", "Google"]
        curr_engine = st.session_state.cfg.get("engine", "Edge (推荐)")
        idx_e = engine_opts.index(curr_engine) if curr_engine in engine_opts else 0
        new_engine = st.selectbox("TTS 引擎", engine_opts, index=idx_e)
        st.session_state.cfg["engine"] = new_engine
        
        # 音色选择逻辑
        if "Edge" in new_engine:
            voice_map = {
                "🇬🇧 英语": {"🇺🇸 Aria (女)": "en-US-AriaNeural", "🇬🇧 Ryan (男)": "en-GB-RyanNeural"},
                "🇫🇷 法语": {"🇫🇷 Henri (男)": "fr-FR-HenriNeural", "🇫🇷 Denise (女)": "fr-FR-DeniseNeural"},
                "🇩🇪 德语": {"🇩🇪 Conrad (男)": "de-DE-ConradNeural", "🇩🇪 Katja (女)": "de-DE-KatjaNeural"},
                "🇷🇺 俄语": {"🇷🇺 Dmitry (男)": "ru-RU-DmitryNeural", "🇷🇺 Svetlana (女)": "ru-RU-SvetlanaNeural"},
            }
            avail_voices = voice_map.get(new_lang, {"Default": "en-US-AriaNeural"})
            v_names = list(avail_voices.keys())
            # 反查当前 voice 对应的 name
            curr_role = st.session_state.cfg["voice_role"]
            default_idx = 0
            for i, (name, code) in enumerate(avail_voices.items()):
                if code == curr_role: default_idx = i
            
            sel_v = st.selectbox("选择发音人", v_names, index=default_idx)
            st.session_state.cfg["voice_role"] = avail_voices[sel_v]
            
        elif "SiliconFlow" in new_engine:
            sf_voices = {
                "Benjamin (英/男)": "benjamin",
                "Bella (美/女)": "bella",
                "Alex (美/男)": "alex"
            }
            st.info("SiliconFlow 仅支持部分英语/中文音色")
            sel_sf = st.selectbox("CosyVoice 音色", list(sf_voices.keys()))
            st.session_state.cfg["voice_role"] = sf_voices[sel_sf]

        st.session_state.cfg["speed"] = st.slider("语速 (Rate)", -50, 50, st.session_state.cfg["speed"], 10)

# ================= 6. 主页面逻辑 =================

if selected_page == "高级设置":
    st.subheader("🛠️ 系统设置")
    
    with st.container(border=True):
        st.markdown("#### 🔑 API 密钥管理")
        st.session_state.cfg["api_key"] = st.text_input(
            "SiliconFlow API Key (用于 AI 翻译/查词/TTS)", 
            value=st.session_state.cfg["api_key"], 
            type="password",
            help="从 cloud.siliconflow.cn 获取"
        )
        st.session_state.cfg["generic_base_url"] = st.text_input(
            "Base URL", 
            value=st.session_state.cfg["generic_base_url"]
        )
    
    with st.container(border=True):
        st.markdown("#### 🧠 模型配置")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.cfg["chat_model"] = st.text_input("Chat 模型", value=st.session_state.cfg["chat_model"])
        with c2:
            st.session_state.cfg["ocr_model"] = st.text_input("OCR 模型", value=st.session_state.cfg["ocr_model"])

elif selected_page == "学习主页":
    # 两栏布局：左侧输入，右侧查词
    col_main, col_side = st.columns([2, 1])
    
    with col_main:
        st.markdown("### 📝 阅读与朗读")
        
        # 输入方式切换
        input_tab1, input_tab2 = st.tabs(["✏️ 文本输入", "📷 拍照识别 (OCR)"])
        
        with input_tab1:
            txt = st.text_area("请输入文章", value=st.session_state.main_text, height=200, placeholder="Paste text here...")
            if st.button("更新文本", key="btn_update_txt"):
                st.session_state.main_text = txt
                st.session_state.trans_text = "" # 清空旧翻译
                st.rerun()
                
        with input_tab2:
            uploaded_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg'])
            if uploaded_file and st.button("开始 OCR 识别"):
                with st.spinner("正在识别文字..."):
                    res_text, err = api_call("ocr", Image.open(uploaded_file), st.session_state.cfg)
                    if res_text:
                        st.session_state.main_text = res_text
                        st.session_state.trans_text = ""
                        st.success("识别成功！")
                        st.rerun()
                    else:
                        st.error(err)
        
        # 操作栏
        if st.session_state.main_text:
            st.markdown("---")
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("▶️ 朗读全文", type="primary", use_container_width=True):
                    with st.spinner("正在合成语音..."):
                        audio_data, err = asyncio.run(get_audio_bytes_mixed(
                            st.session_state.main_text,
                            st.session_state.cfg["engine"],
                            st.session_state.cfg["voice_role"],
                            st.session_state.cfg["speed"],
                            st.session_state.cfg
                        ))
                        if audio_data:
                            st.session_state.audio_data = audio_data
                            st.rerun()
                        else:
                            st.error(f"合成失败: {err}")
            
            with c2:
                if st.button("🌐 全文翻译", use_container_width=True):
                    with st.spinner("AI 翻译中..."):
                        trans, err = api_call("trans", st.session_state.main_text, st.session_state.cfg)
                        if trans:
                            st.session_state.trans_text = trans
                            st.rerun()
                        else:
                            st.error(err)

            # 结果展示区
            if st.session_state.trans_text:
                st.info(f"**参考译文：**\n\n{st.session_state.trans_text}")
            
            if st.session_state.audio_data:
                st.audio(st.session_state.audio_data, format="audio/mp3")
                # 下载按钮
                b64_audio = base64.b64encode(st.session_state.audio_data).decode()
                filename = get_smart_filename(st.session_state.main_text)
                href = f'<a href="data:audio/mp3;base64,{b64_audio}" download="{filename}" style="text-decoration:none;">📥 点击下载音频</a>'
                st.markdown(href, unsafe_allow_html=True)

    with col_side:
        st.markdown("### 🔍 智能查词")
        with st.container(border=True):
            q_word = st.text_input("查词", placeholder="输入单词...")
            if st.button("查询 & 解析", use_container_width=True):
                if q_word:
                    with st.spinner("查询中..."):
                        info, err = api_call("lookup", q_word, st.session_state.cfg)
                        if info:
                            info['word'] = q_word # 确保有 word 字段
                            st.session_state.last_lookup = info
                            # 自动生成发音
                            ab, _ = asyncio.run(get_audio_bytes_mixed(q_word, "Edge (推荐)", "en-US-AriaNeural", 0, st.session_state.cfg))
                            st.session_state.lookup_audio = ab
                            
                            # 自动加入生词本 (去重)
                            if not any(w['word'] == q_word for w in st.session_state.vocab):
                                new_item = {
                                    "word": q_word,
                                    "ipa": info.get("ipa", ""),
                                    "zh": info.get("zh", ""),
                                    "ru": info.get("ru", ""),
                                    "date": datetime.now().strftime("%Y-%m-%d")
                                }
                                st.session_state.vocab.insert(0, new_item)
                                save_vocab(st.session_state.vocab)
                            st.rerun()
                        else:
                            st.error(err)

        # 显示查词结果卡片
        if st.session_state.last_lookup:
            info = st.session_state.last_lookup
            st.markdown(f"""
            <div class="lookup-card">
                <h3 style="color:#007aff; margin-bottom:0;">{info['word']}</h3>
                <div style="color:#666; font-family:monospace; margin-bottom:10px;">{info.get('ipa', '')}</div>
                <div style="margin-bottom:5px;"><b>🇨🇳 中文：</b>{info.get('zh', 'N/A')}</div>
                <div><b>🇷🇺 俄语：</b>{info.get('ru', 'N/A')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.session_state.lookup_audio:
                st.audio(st.session_state.lookup_audio, format="audio/mp3", autoplay=True)

elif selected_page == "单词本":
    st.subheader(f"📓 我的生词本 ({len(st.session_state.vocab)})")
    
    if not st.session_state.vocab:
        st.caption("暂无生词，快去阅读页面查词吧！")
    else:
        # 顶部工具栏
        c_tool1, c_tool2 = st.columns([1, 4])
        with c_tool1:
            if st.button("📤 导出 Anki 包", type="primary"):
                # 收集勾选的单词
                selected_items = []
                for i, item in enumerate(st.session_state.vocab):
                    if st.session_state.get(f"chk_{i}", False):
                        selected_items.append(item)
                
                if not selected_items:
                    st.warning("请先勾选至少一个单词！")
                else:
                    # 异步生成
                    anki_io = asyncio.run(create_anki_package(selected_items, st.session_state.cfg))
                    st.download_button(
                        label="⬇️ 点击下载 .apkg",
                        data=anki_io,
                        file_name=f"vocab_export_{datetime.now().strftime('%m%d')}.apkg",
                        mime="application/octet-stream"
                    )

        st.divider()
        
        # 列表头
        h1, h2, h3, h4, h5 = st.columns([0.5, 2, 3, 1, 1])
        h1.markdown("选")
        h2.markdown("单词")
        h3.markdown("释义 (中/俄)")
        h4.markdown("发音")
        h5.markdown("操作")
        
        # 列表内容
        for i, item in enumerate(st.session_state.vocab):
            c1, c2, c3, c4, c5 = st.columns([0.5, 2, 3, 1, 1])
            with c1: st.checkbox("", key=f"chk_{i}")
            with c2: st.markdown(f"**{item['word']}**\n<br><span style='color:grey;font-size:12px'>{item.get('ipa','')}</span>", unsafe_allow_html=True)
            with c3: st.markdown(f"🇨🇳 {item.get('zh','')}\n<br>🇷🇺 {item.get('ru','')}", unsafe_allow_html=True)
            
            with c4:
                # 播放逻辑：点击后将音频放入 SessionState 并刷新，依靠 autoplay 播放
                if st.button("🔊", key=f"play_{i}"):
                    # 简易策略：如果是俄语单词用俄语发音，否则默认英语
                    # 这里简单判断：如果单词里有西里尔字母则为俄语
                    is_ru = bool(re.search('[а-яА-Я]', item['word']))
                    v_role = "ru-RU-DmitryNeural" if is_ru else "en-US-AriaNeural"
                    
                    audio_bytes, _ = asyncio.run(get_audio_bytes_mixed(item['word'], "Edge (推荐)", v_role, 0, st.session_state.cfg))
                    if audio_bytes:
                        st.session_state.vocab_audio_cache[item['word']] = audio_bytes
                        st.session_state.playing_word_idx = i # 标记当前正在播放的索引
                        st.rerun()

            with c5:
                if st.button("🗑️", key=f"del_{i}"):
                    st.session_state.vocab.pop(i)
                    save_vocab(st.session_state.vocab)
                    st.rerun()
            
            # 仅在当前行渲染不可见的音频播放器以触发 Autoplay
            if st.session_state.playing_word_idx == i and item['word'] in st.session_state.vocab_audio_cache:
                st.audio(st.session_state.vocab_audio_cache[item['word']], format="audio/mp3", autoplay=True)