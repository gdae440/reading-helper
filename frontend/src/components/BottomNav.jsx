import { BookOpen, Library, Settings } from 'lucide-react';

const BottomNav = ({ currentView, setView }) => {
  const navItems = [
    { id: 'reader', label: '学习', icon: <BookOpen size={24} /> },
    { id: 'vocab', label: '生词', icon: <Library size={24} /> },
    { id: 'settings', label: '设置', icon: <Settings size={24} /> },
  ];

  return (
    <div className="bottom-nav">
      {navItems.map((item) => (
        <button
          key={item.id}
          className={`bottom-nav-item ${currentView === item.id ? 'active' : ''}`}
          onClick={() => setView(item.id)}
        >
          <div className="icon-wrapper">{item.icon}</div>
          <span className="nav-label">{item.label}</span>
        </button>
      ))}
    </div>
  );
};

export default BottomNav;