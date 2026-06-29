import { Calendar } from 'lucide-react';
import InfoTooltip from './InfoTooltip';

interface DateRangeFilterProps {
  startDate: string;
  endDate: string;
  onStartChange: (d: string) => void;
  onEndChange: (d: string) => void;
}

const PRESETS = [
  { label: 'Last 7d', days: 7 },
  { label: 'Last 30d', days: 30 },
  { label: 'Last 90d', days: 90 },
  { label: 'Last 6mo', days: 180 },
  { label: 'Last 1yr', days: 365 },
];

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DateRangeFilter({ startDate, endDate, onStartChange, onEndChange }: DateRangeFilterProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2">
        <Calendar size={16} className="text-[var(--color-text-muted)]" />
        <span className="text-sm font-medium text-[var(--color-text-secondary)]">Date Range</span>
        <InfoTooltip text="Filter all charts on this page by date range. Presets calculate from today's date. Custom dates can be entered directly." />
      </div>
      <input
        type="date"
        value={startDate}
        onChange={(e) => onStartChange(e.target.value)}
        className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
      />
      <span className="text-[var(--color-text-muted)]">to</span>
      <input
        type="date"
        value={endDate}
        onChange={(e) => onEndChange(e.target.value)}
        className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
      />
      <div className="flex gap-1.5">
        {PRESETS.map(p => (
          <button
            key={p.label}
            onClick={() => { onStartChange(daysAgo(p.days)); onEndChange(today()); }}
            className="px-2.5 py-1 text-xs rounded-full bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
              text-[var(--color-text-secondary)] hover:bg-[var(--color-primary)] hover:text-white hover:border-[var(--color-primary)] transition-colors"
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
