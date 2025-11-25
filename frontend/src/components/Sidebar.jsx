import { BookOpen, Settings, Library, Mic } from 'lucide-react';

const Sidebar = ({ currentView, setView }) => {
  const menuItems = [
    { id: 'reader', label: '学习主页', icon: <BookOpen size={20} /> },
    { id: 'vocab', label: '生词本', icon: <Library size={20} /> },
    { id: 'settings', label: '设置', icon: <Settings size={20} /> },
  ];

  return (
    <div className="sidebar">
      <div className="logo-area">
        <Mic size={28} color="#007AFF" />
        <span className="app-title">跟读助手 Pro</span>
      </div>
      <nav className="nav-menu">
        {menuItems.map((item) => (
          <button key={item.id} onClick={() => setView(item.id)}
            className={`nav-item ${currentView === item.id ? 'active' : ''}`}>
            {item.icon}<span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
};
export default Sidebar;