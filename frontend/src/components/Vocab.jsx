import { useState, useEffect } from 'react';
import axios from 'axios';
import { Trash2, Volume2, Loader2, Download, CheckSquare, Square } from 'lucide-react';

const Vocab = () => {
  const [vocabList, setVocabList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [playingWord, setPlayingWord] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [selectedWords, setSelectedWords] = useState(new Set());

  const API_URL = `http://${window.location.hostname}:8000`;

  useEffect(() => { fetchVocab(); }, [API_URL]);

  const fetchVocab = async () => {
    try {
      const res = await axios.get(`${API_URL}/vocab`);
      setVocabList(res.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const toggleSelect = (word) => {
    const newSet = new Set(selectedWords);
    if (newSet.has(word)) newSet.delete(word); else newSet.add(word);
    setSelectedWords(newSet);
  };

  const toggleAll = () => {
    if (selectedWords.size === vocabList.length) setSelectedWords(new Set());
    else setSelectedWords(new Set(vocabList.map(v => v.word)));
  };

  const handleExportSelected = async () => {
    if (selectedWords.size === 0) return alert("请先勾选要导出的单词");
    setExporting(true);
    try {
      const apiKey = localStorage.getItem('sf_api_key') || "";
      const response = await axios.post(`${API_URL}/vocab/anki_export`, 
        { words: Array.from(selectedWords), api_key: apiKey }, { responseType: 'blob' }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a'); link.href = url;
      link.setAttribute('download', `Anki_Select.apkg`);
      document.body.appendChild(link); link.click(); link.remove();
    } catch (e) { alert("导出失败"); } finally { setExporting(false); }
  };

  const handleDelete = async (word) => {
    if (!confirm(`删除 "${word}"?`)) return;
    try {
      const res = await axios.post(`${API_URL}/vocab/delete`, { word });
      setVocabList(res.data.vocab);
      if (selectedWords.has(word)) { const newSet = new Set(selectedWords); newSet.delete(word); setSelectedWords(newSet); }
    } catch (e) { alert("删除失败"); }
  };

  // 🔥 修复 4: 智能发音选择 (补救旧数据)
  // 如果 lang 字段不准，就检查 word 是否包含俄文字母，或者 ru 释义是否存在
  const detectVoice = (item) => {
    const lang = item.lang || "";
    const word = item.word || "";
    const ruTrans = item.ru || "";

    // 1. 优先信 lang 字段
    if (lang.includes("法") || lang.includes("fr")) return "fr-FR-HenriNeural";
    if (lang.includes("德") || lang.includes("de")) return "de-DE-ConradNeural";
    
    // 2. 如果 lang 没得选，检测单词本身是否含俄文
    if (/[а-яА-ЯЁё]/.test(word)) return "ru-RU-DmitryNeural";
    
    // 3. 如果单词也没特征，看有没有俄语释义 (且没有中文释义干扰)
    if (ruTrans && !lang.includes("英")) return "ru-RU-DmitryNeural";

    return "en-GB-RyanNeural"; // 默认
  };

  const handlePlay = async (item) => {
    setPlayingWord(item.word);
    try {
      const voiceRole = detectVoice(item);
      const res = await axios.post(`${API_URL}/tts`, {
        text: item.word, engine: "Edge (推荐)", voice_role: voiceRole, speed: 0
      });
      new Audio("data:audio/mpeg;base64," + res.data).play();
    } catch (e) {} finally { setPlayingWord(null); }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div style={{display:'flex', alignItems:'center', gap:'12px'}}>
          <h2>📚 我的生词本</h2>
          <span style={{color:'#86868B', fontSize:'14px'}}>{selectedWords.size} / {vocabList.length}</span>
        </div>
        {vocabList.length > 0 && (
          <div className="vocab-toolbar">
             <button className="btn btn-text" onClick={toggleAll}>{selectedWords.size === vocabList.length ? '取消' : '全选'}</button>
             <button className="btn btn-outline" onClick={handleExportSelected} disabled={exporting || selectedWords.size===0}>
               {exporting ? <Loader2 className="spin" size={16}/> : <Download size={16}/>} 导出
             </button>
          </div>
        )}
      </div>

      {loading ? <div style={{textAlign:'center', padding:'40px'}}><Loader2 className="spin"/></div> : 
       vocabList.length === 0 ? <div style={{textAlign:'center', padding:'60px', color:'#C7C7CC'}}>暂无生词</div> : (
        <div className="vocab-list">
          {vocabList.map((item, idx) => (
            <div key={idx} className="vocab-item" style={{borderColor: selectedWords.has(item.word)?'#007AFF':'#E5E5EA', background: selectedWords.has(item.word)?'#F2F9FF':'#F9F9FA'}}>
              <div style={{display:'flex', alignItems:'center', gap:'15px', flex:1, minWidth:0}}>
                <div onClick={() => toggleSelect(item.word)} style={{cursor:'pointer', color: selectedWords.has(item.word)?'#007AFF':'#C7C7CC', flexShrink:0}}>
                  {selectedWords.has(item.word) ? <CheckSquare size={24} fill="#007AFF" color="white"/> : <Square size={24}/>}
                </div>
                <div style={{minWidth:0, overflow:'hidden'}}>
                  <div className="word-row"><span className="word-text">{item.word}</span><span className="ipa-text">[{item.ipa}]</span></div>
                  <div className="trans-row"><span>🇨🇳 {item.zh}</span>{item.ru && <span style={{marginLeft:'10px'}}>🇷🇺 {item.ru}</span>}</div>
                </div>
              </div>
              <div className="vocab-actions">
                <button className="icon-btn" onClick={() => handlePlay(item)}>{playingWord === item.word ? <Loader2 size={18} className="spin"/> : <Volume2 size={18}/>}</button>
                <button className="icon-btn delete" onClick={() => handleDelete(item.word)}><Trash2 size={18}/></button>
              </div>
            </div>
          ))}
        </div>
      )}
      <style>{`
        .btn-text { background: none; border: none; color: #007AFF; font-weight: 500; cursor: pointer; padding: 0 10px; }
        .btn-outline { background: white; border: 1px solid #D1D1D6; color: #1D1D1F; padding: 6px 12px; border-radius: 10px; font-weight: 500; font-size: 13px; display: flex; align-items: center; gap: 6px; }
        .btn-outline:disabled { opacity: 0.5; cursor: not-allowed; }
        .vocab-toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
        .vocab-list { display: flex; flex-direction: column; gap: 10px; }
        .vocab-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-radius: 12px; border: 1px solid #E5E5EA; transition: all 0.2s; }
        .word-text { font-size: 17px; font-weight: 600; color: #1D1D1F; margin-right: 8px; }
        .ipa-text { color: #86868B; font-family: Arial; font-size: 13px; }
        .trans-row { margin-top: 4px; font-size: 13px; color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .vocab-actions { display: flex; gap: 8px; flex-shrink: 0; margin-left: 10px; }
        .icon-btn { width: 36px; height: 36px; border-radius: 50%; border: none; background: #fff; cursor: pointer; color: #007AFF; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; justify-content: center; align-items: center; padding: 0; }
        .icon-btn.delete { color: #FF3B30; }
        .icon-btn.active { transform: scale(0.95); background: #F2F2F7; }
      `}</style>
    </div>
  );
};
export default Vocab;