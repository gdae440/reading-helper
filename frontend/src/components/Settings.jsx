import { useState, useEffect } from 'react';
import { Save, Key, Globe, Cpu, ScanText } from 'lucide-react';

const Settings = () => {
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [chatModel, setChatModel] = useState('');
  const [ocrModel, setOcrModel] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    setApiKey(localStorage.getItem('sf_api_key') || '');
    setBaseUrl(localStorage.getItem('sf_base_url') || 'https://api.siliconflow.cn/v1');
    setChatModel(localStorage.getItem('sf_chat_model') || 'deepseek-ai/DeepSeek-V3');
    setOcrModel(localStorage.getItem('sf_ocr_model') || 'Qwen/Qwen2.5-VL-72B-Instruct');
  }, []);

  const handleSave = () => {
    localStorage.setItem('sf_api_key', apiKey);
    localStorage.setItem('sf_base_url', baseUrl);
    localStorage.setItem('sf_chat_model', chatModel);
    localStorage.setItem('sf_ocr_model', ocrModel);
    
    setStatus('✅ 配置已保存');
    setTimeout(() => setStatus(''), 2000);
  };

  return (
    <div className="card">
      <h2>⚙️ 高级设置</h2>
      
      <div className="settings-container">
        <div className="form-group">
          <label><Key size={16} style={{marginRight:6, verticalAlign:'text-bottom'}}/> API Key</label>
          <input 
            type="password" className="form-control" placeholder="sk-..." 
            value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            style={{fontFamily: 'monospace'}}
          />
        </div>

        <div className="form-group">
          <label><Globe size={16} style={{marginRight:6, verticalAlign:'text-bottom'}}/> API Base URL (可选)</label>
          <input 
            type="text" className="form-control" placeholder="https://api.siliconflow.cn/v1" 
            value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
          />
          <p className="hint-text">默认: https://api.siliconflow.cn/v1</p>
        </div>

        <div style={{height: '1px', background: '#E5E5EA', margin: '20px 0'}}></div>

        {/* 🔥 优化: 移除 flexWrap, 在手机上使用 gap 控制间距，使其并排或堆叠更自然 */}
        <div className="models-row">
          <div className="form-group" style={{flex:1}}>
            <label><Cpu size={16} style={{marginRight:6, verticalAlign:'text-bottom'}}/> Chat 模型</label>
            <input 
              type="text" className="form-control" placeholder="deepseek-ai..." 
              value={chatModel} onChange={(e) => setChatModel(e.target.value)}
            />
          </div>
          <div className="form-group" style={{flex:1}}>
            <label><ScanText size={16} style={{marginRight:6, verticalAlign:'text-bottom'}}/> OCR 模型</label>
            <input 
              type="text" className="form-control" placeholder="Qwen/Qwen..." 
              value={ocrModel} onChange={(e) => setOcrModel(e.target.value)}
            />
          </div>
        </div>

        <div style={{marginTop: '30px'}}>
          <button className="btn btn-primary" onClick={handleSave}>
            <Save size={18} /> 保存配置
          </button>
          {status && <span style={{marginLeft:'15px', color: '#34C759', fontWeight: 500}}>{status}</span>}
        </div>
      </div>
      
      <style>{`
        .models-row { display: flex; gap: 20px; }
        @media (max-width: 768px) {
           /* 手机上让两个模型输入框并排，gap 稍微小一点 */
           .models-row { gap: 10px; }
           .hint-text { font-size: 12px; }
        }
      `}</style>
    </div>
  );
};
export default Settings;