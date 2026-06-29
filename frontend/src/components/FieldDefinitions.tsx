import { BookOpen, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

interface FieldDef {
  name: string;
  description: string;
}

interface FieldDefinitionsProps {
  title?: string;
  fields: FieldDef[];
}

export default function FieldDefinitions({ title = 'Field Definitions', fields }: FieldDefinitionsProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-4 border border-[var(--color-border)] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-card-hover)] transition-colors"
      >
        <span className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-secondary)]">
          <BookOpen size={14} />
          {title}
        </span>
        {open ? <ChevronUp size={14} className="text-[var(--color-text-muted)]" /> : <ChevronDown size={14} className="text-[var(--color-text-muted)]" />}
      </button>
      {open && (
        <div className="px-4 py-3 bg-white space-y-2">
          {fields.map(f => (
            <div key={f.name} className="text-xs">
              <span className="font-mono font-semibold text-[var(--color-primary)]">{f.name}</span>
              <span className="text-[var(--color-text-secondary)]"> — {f.description}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
