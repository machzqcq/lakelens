import { Info } from 'lucide-react';
import { useState } from 'react';

interface InfoTooltipProps {
  text: string;
  className?: string;
}

export default function InfoTooltip({ text, className = '' }: InfoTooltipProps) {
  const [show, setShow] = useState(false);

  return (
    <span className={`relative inline-flex items-center ${className}`}>
      <button
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onClick={() => setShow(!show)}
        className="text-[var(--color-text-muted)] hover:text-[var(--color-primary)] transition-colors ml-1"
        aria-label="More info"
      >
        <Info size={14} />
      </button>
      {show && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 p-3
          bg-white border border-[var(--color-border)] rounded-xl shadow-lg
          text-xs text-[var(--color-text-secondary)] z-50 leading-relaxed">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-[var(--color-border)]" />
        </div>
      )}
    </span>
  );
}
