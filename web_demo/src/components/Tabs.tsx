interface Tab {
  id: string;
  label: string;
  disabled?: boolean;
}

interface TabsProps {
  tabs: Tab[];
  activeId: string;
  onChange: (id: string) => void;
}

export default function Tabs({ tabs, activeId, onChange }: TabsProps) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={t.id === activeId}
          disabled={t.disabled}
          className={`tab${t.id === activeId ? " tab--active" : ""}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
