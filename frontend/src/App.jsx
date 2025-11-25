import { useState } from 'react';
import Sidebar from './components/Sidebar';
import BottomNav from './components/BottomNav'; // 新增
import Settings from './components/Settings';
import Reader from './components/Reader';
import Vocab from './components/Vocab';
import './App.css';

function App() {
  const [currentView, setView] = useState('reader');

  const renderContent = () => {
    switch (currentView) {
      case 'reader': return <Reader />;
      case 'settings': return <Settings />;
      case 'vocab': return <Vocab />;
      default: return <div>404 Not Found</div>;
    }
  };

  return (
    <div className="app-layout">
      {/* 桌面端显示侧边栏 */}
      <Sidebar currentView={currentView} setView={setView} />
      
      {/* 主内容区 */}
      <main className="main-content">
        {renderContent()}
      </main>

      {/* 移动端显示底部导航 */}
      <BottomNav currentView={currentView} setView={setView} />
    </div>
  );
}

export default App;