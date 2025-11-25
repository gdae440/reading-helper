import { useState, useEffect } from 'react';
import axios from 'axios';
import { Play, Loader2, Volume2, Gauge, Image as ImageIcon, Search, PlusCircle, Check, FileText, AlertCircle, BookOpen, Download, Languages, Undo2 } from 'lucide-react';

const Reader = () => {
  const [text, setText] = useState(''); // 当前显示的文本
  const [originalText, setOriginalText] = useState(''); // 备份原文
  const [isTranslated, setIsTranslated] = useState(false); // 是否在显示译文
  
  const [mode, setMode] = useState('text');
  const [loading, setLoading] = useState(false);
  const [transLoading, setTransLoading] = useState(false);
  const [audioUrl, setAudioUrl] = useState(null);
  const [error, setError] = useState('');
  
  const [lookupWord, setLookupWord] = useState('');
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [isAdded, setIsAdded] = useState(false);

  const [engine, setEngine] = useState('Edge (推荐)');
  const [voice, setVoice] = useState('en-GB-RyanNeural'); 
  const [speed, setSpeed] = useState(0);
  
  const [voiceOptions, setVoiceOptions] = useState({ edge: {}, siliconflow: {}, google_langs: {} });
  const [voicesLoaded, setVoicesLoaded] = useState(false);

  const API_BASE_URL = `http://${window.location.hostname}:8000`;

  const getConfig = () => ({
    api_key: localStorage.getItem('sf_api_key'),
    base_url: localStorage.getItem('sf_base_url'),
    chat_model: localStorage.getItem('sf_chat_model'),
    ocr_model: localStorage.getItem('sf_ocr_model')
  });

  useEffect(() => {
    axios.get(`${API_BASE_URL}/config/voices`).then(res => {
      setVoiceOptions(res.data);
      setVoicesLoaded(true);
    }).catch(e => console.error(e));
  }, [API_BASE_URL]);

  const handleTextChange = (newText) => {
    setText(newText);
    // 如果用户手动修改了文本，且当前是翻译状态，视为用户想回到原文编辑模式 (逻辑可选)
    if (!isTranslated) {
        // 仅在 Edge 引擎下自动切换
        if (!engine.includes('Edge')) return;
        const hasRussian = /[а-яА-ЯЁё]/.test(newText);
        const hasChinese = /[一-龥]/.test(newText);
        if (hasRussian) { if (voice !== 'ru-RU-DmitryNeural') setVoice('ru-RU-DmitryNeural'); }
        else if (hasChinese) { if (voice !== 'zh-CN-XiaoxiaoNeural') setVoice('zh-CN-XiaoxiaoNeural'); }
        else { if (voice.includes('ru-RU') || voice.includes('zh-CN')) setVoice('en-GB-RyanNeural'); }
    }
  };

  const renderVoiceOptions = () => {
    if (!voicesLoaded) return <option>加载中...</option>;
    if (engine.includes('Edge')) {
      return Object.entries(voiceOptions.edge || {}).map(([lang, voices]) => (
        <optgroup label={lang} key={lang}>{voices.map(v => <option key={v[0]} value={v[0]}>{v[1]}</option>)}</optgroup>
      ));
    } else if (engine.includes('SiliconFlow')) {
      return Object.entries(voiceOptions.siliconflow || {}).map(([name, id]) => <option key={id} value={id}>{name}</option>);
    } else if (engine.includes('Google')) {
      return Object.entries(voiceOptions.google_langs || {}).map(([name, code]) => <option key={code} value={name}>{name}</option>);
    }
    return <option>无可用音色</option>;
  };

  const handlePlay = async () => {
    const cfg = getConfig();
    if (engine.includes('SiliconFlow') && !cfg.api_key) { setError("请在设置页填写 API Key"); return; }
    setLoading(true); setError(''); setAudioUrl(null);
    try {
      const res = await axios.post(`${API_BASE_URL}/tts`, { text, engine, voice_role: voice, speed, api_key: cfg.api_key, base_url: cfg.base_url });
      const bytes = atob(res.data);
      const ia = new Uint8Array(new ArrayBuffer(bytes.length));
      for (let i = 0; i < bytes.length; i++) ia[i] = bytes.charCodeAt(i);
      const blob = new Blob([ia], { type: 'audio/mpeg' });
      setAudioUrl(URL.createObjectURL(blob));
    } catch (e) { setError('生成失败: ' + (e.response?.data?.detail || e.message)); } finally { setLoading(false); }
  };

  // 🔥 新增: 全文翻译功能
  const handleTranslate = async () => {
    if (isTranslated) {
        // 切换回原文
        setText(originalText);
        setIsTranslated(false);
        return;
    }
    
    if (!text.trim()) return;
    const cfg = getConfig();
    if (!cfg.api_key) { alert("翻译需要配置 API Key"); return; }

    setTransLoading(true);
    setOriginalText(text); // 保存原文
    
    try {
        const res = await axios.post(`${API_BASE_URL}/translate`, { 
            text, api_key: cfg.api_key, base_url: cfg.base_url, chat_model: cfg.chat_model 
        });
        setText(res.data.text);
        setIsTranslated(true);
    } catch (e) {
        alert("翻译失败: " + (e.response?.data?.detail || e.message));
    } finally {
        setTransLoading(false);
    }
  };

  const handleOCR = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    const cfg = getConfig(); if (!cfg.api_key) { alert("OCR 需要 API Key"); return; }
    setLoading(true); setError('');
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const base64Str = reader.result.split(',')[1];
        const res = await axios.post(`${API_BASE_URL}/ocr`, { image_base64: base64Str, api_key: cfg.api_key, base_url: cfg.base_url, ocr_model: cfg.ocr_model });
        handleTextChange(res.data.text); setMode('text');
      } catch (err) { setError("OCR 失败: " + err.message); } finally { setLoading(false); }
    };
    reader.readAsDataURL(file);
  };

  const handleLookup = async () => {
    if (!lookupWord) return;
    const cfg = getConfig(); if (!cfg.api_key) { alert("查词需要 API Key"); return; }
    setLookupLoading(true); setLookupResult(null); setIsAdded(false);
    try {
      const res = await axios.post(`${API_BASE_URL}/lookup`, { word: lookupWord, api_key: cfg.api_key, base_url: cfg.base_url, chat_model: cfg.chat_model });
      setLookupResult({...res.data, word: lookupWord});
    } catch (e) { alert("查词失败"); } finally { setLookupLoading(false); }
  };

  const saveToVocab = async () => {
    if (!lookupResult) return;
    try { await axios.post(`${API_BASE_URL}/vocab/add`, lookupResult); setIsAdded(true); } catch (e) { alert("保存失败"); }
  };

  return (
    <div className="reader-layout">
      <div className="card reader-main">
        <div className="card-header">
          <div style={{display:'flex', gap:'10px'}}>
             <button className={`tab-btn ${mode==='text'?'active':''}`} onClick={()=>setMode('text')}><FileText size={16}/> 文本</button>
             <button className={`tab-btn ${mode==='ocr'?'active':''}`} onClick={()=>setMode('ocr')}><ImageIcon size={16}/> OCR</button>
          </div>
          <div className="toolbar-mini">
             <select value={engine} onChange={(e)=>setEngine(e.target.value)} className="mini-select"><option>Edge (推荐)</option><option>SiliconFlow</option><option>Google</option></select>
             {voicesLoaded && <select value={voice} onChange={(e)=>setVoice(e.target.value)} className="mini-select" style={{maxWidth:'120px'}}>{renderVoiceOptions()}</select>}
             <div className="speed-mini"><Gauge size={14} color="#666"/><input type="range" min="-50" max="50" step="10" value={speed} onChange={e=>setSpeed(Number(e.target.value))} style={{width:'120px'}}/></div>
          </div>
        </div>
        <div className="form-group" style={{minHeight: '300px'}}>
          {mode === 'text' ? <textarea className="form-control text-editor" rows="12" value={text} onChange={(e) => handleTextChange(e.target.value)} placeholder="在此粘贴文本，我会自动识别语言..."/> : 
          <div className="ocr-upload-area"><ImageIcon size={48} color="#D1D1D6"/><p>点击上传图片</p><input type="file" accept="image/*" onChange={handleOCR} className="file-input-overlay"/></div>}
        </div>
        <div className="action-area">
          {/* 播放按钮 */}
          <button className="btn btn-primary" onClick={handlePlay} disabled={loading || transLoading}>
            {loading ? <Loader2 className="spin" size={20} /> : <Play size={20} fill="currentColor" />} 
            {loading ? ' 生成中...' : ' 朗读文本'}
          </button>
          
          {/* 🔥 翻译按钮 */}
          <button className="btn btn-secondary" onClick={handleTranslate} disabled={transLoading || loading} style={{marginLeft: '10px'}}>
            {transLoading ? <Loader2 className="spin" size={20} /> : (isTranslated ? <Undo2 size={20} /> : <Languages size={20} />)}
            {transLoading ? ' 翻译中...' : (isTranslated ? ' 显示原文' : ' 翻译全文')}
          </button>
        </div>
        {error && <div className="error-message"><AlertCircle size={16}/> {error}</div>}
        {audioUrl && <div className="audio-player-box"><div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'12px'}}><div className="audio-label"><Volume2 size={16}/> 语音已生成</div><a href={audioUrl} download={`read_aloud_${Date.now()}.mp3`} className="download-link"><Download size={16}/> 下载 MP3</a></div><audio controls autoPlay src={audioUrl} className="native-audio" /></div>}
      </div>

      <div className="card reader-side">
         <h3>🔍 快速查词</h3>
         <div style={{display:'flex', gap:'8px', marginBottom:'20px', width: '100%'}}>
            <input className="form-control" style={{flex:1, minWidth:0}} placeholder="输入单词..." value={lookupWord} onChange={e=>{setLookupWord(e.target.value); setIsAdded(false);}} onKeyDown={e => e.key === 'Enter' && handleLookup()}/>
            <button className="btn btn-primary" style={{padding:'0', width:'44px', display:'flex', justifyContent:'center', alignItems:'center', flexShrink: 0}} onClick={handleLookup} disabled={lookupLoading}>{lookupLoading ? <Loader2 className="spin" size={20}/> : <Search size={20}/>}</button>
         </div>
         {lookupResult ? (
           <div className="lookup-result">
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'start'}}>
                 <div><div style={{fontSize:'20px', fontWeight:'bold'}}>{lookupResult.word}</div><div style={{color:'#666', fontSize:'14px', fontFamily:'Arial'}}>[{lookupResult.ipa}]</div></div>
                 <button className="icon-btn-add" onClick={saveToVocab} title="加入生词本" disabled={isAdded}>
                   {isAdded ? <Check size={24} color="#34C759"/> : <PlusCircle size={24}/>}
                 </button>
              </div>
              <div className="trans-box"><div style={{marginBottom:'6px'}}><b>中:</b> {lookupResult.zh}</div><div><b>俄:</b> {lookupResult.ru}</div></div>
           </div>
         ) : (
           <div style={{textAlign:'center', color:'#C7C7CC', marginTop:'40px'}}><BookOpen size={48} style={{opacity:0.3}}/><p style={{fontSize:'14px', marginTop:'10px'}}>AI 智能词典</p></div>
         )}
      </div>
      <style>{`
        .tab-btn { border: none; background: none; padding: 8px 12px; cursor: pointer; color: #86868B; font-weight: 600; display: flex; gap: 6px; align-items: center; border-radius: 8px; }
        .tab-btn.active { background: #E5F1FF; color: #007AFF; }
        .toolbar-mini { display: flex; gap: 8px; align-items: center; }
        .mini-select { border: 1px solid #E5E5EA; padding: 4px; border-radius: 6px; font-size: 12px; }
        .speed-mini { display: flex; align-items: center; gap: 4px; border: 1px solid #E5E5EA; padding: 0 6px; border-radius: 6px; height: 26px; }
        .ocr-upload-area { border: 2px dashed #E5E5EA; border-radius: 12px; height: 100%; min-height: 280px; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #86868B; position: relative; cursor: pointer; transition: all 0.2s; background-color: #FAFAFA; }
        .ocr-upload-area:hover { border-color: #007AFF; background: #F2F9FF; }
        .file-input-overlay { position: absolute; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
        .lookup-result { animation: fadeIn 0.3s ease; }
        .icon-btn-add { border: none; background: none; color: #34C759; cursor: pointer; padding: 0; }
        .icon-btn-add:hover { opacity: 0.8; transform: scale(1.1); transition: 0.2s; }
        .trans-box { margin-top: 15px; padding: 12px; background: #F9F9FA; border-radius: 8px; font-size: 14px; line-height: 1.5; border: 1px solid #F0F0F0; }
        .download-link { display: flex; align-items: center; gap: 4px; color: #007AFF; text-decoration: none; font-size: 13px; font-weight: 500; }
        .download-link:hover { text-decoration: underline; }
        .btn-secondary { background: #E5E5EA; color: #1D1D1F; }
        .btn-secondary:hover { background: #D1D1D6; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  );
};
export default Reader;