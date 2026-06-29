/**
 * DateRangeDimensionPicker — the canonical filter strip for any dashboard
 * page that wants:
 *   1. a date range (start + end + preset buttons), and
 *   2. a dimension / time-grain toggle (segmented buttons).
 *
 * Modelled on the Cost Explorer filter row but split out so every page can
 * adopt the same look + state shape. Two callbacks: `onDateChange` (start,
 * end) and `onDimensionChange` (key). State is owned by the parent so the
 * picker stays controlled and the TanStack Query cache key can include the
 * range/dimension verbatim.
 *
 * Usage:
 *   const [start, setStart] = useState(daysAgo(180));
 *   const [end,   setEnd]   = useState(today());
 *   const [dim,   setDim]   = useState<'month'|'week'|'day'>('month');
 *
 *   <DateRangeDimensionPicker
 *     startDate={start} endDate={end}
 *     onDateChange={(s, e) => { setStart(s); setEnd(e); }}
 *     dimension={dim}
 *     dimensions={[
 *       { key: 'day',   label: 'Day' },
 *       { key: 'week',  label: 'Week' },
 *       { key: 'month', label: 'Month' },
 *     ]}
 *     onDimensionChange={(k) => setDim(k as typeof dim)}
 *   />
 *
 *   const q = useQuery({
 *     queryKey: ['adoption', start, end, dim],
 *     queryFn: () => qi.adoptionTrend(start, end, dim),
 *   });
 *
 * The component intentionally renders nothing for the dimension row when
 * `dimensions` is empty / undefined — so pages that only want the date
 * range can use it without the extra row appearing.
 */
import { Calendar, LayoutGrid } from 'lucide-react';
import InfoTooltip from './InfoTooltip';

export interface DimensionOption {
  key: string;
  label: string;
  /** Optional tooltip surfaced next to the dimension label. */
  tooltip?: string;
}

interface Props {
  startDate: string;
  endDate: string;
  onDateChange: (startDate: string, endDate: string) => void;
  /** Active dimension key; required when `dimensions` is non-empty. */
  dimension?: string;
  dimensions?: DimensionOption[];
  onDimensionChange?: (key: string) => void;
  /** Override the "Dimension" label (e.g. "Time grain", "Group by"). */
  dimensionLabel?: string;
  /** Override the date-range label. */
  dateLabel?: string;
  /** Hide the date row entirely — useful when a parent already renders a
   *  page-level date strip and a child card just wants the grain picker. */
  showDateRange?: boolean;
}

const PRESETS = [
  { label: 'Last 7d',   days: 7   },
  { label: 'Last 30d',  days: 30  },
  { label: 'Last 90d',  days: 90  },
  { label: 'Last 6mo',  days: 180 },
  { label: 'Last 1yr',  days: 365 },
];

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export { daysAgo, today };

export default function DateRangeDimensionPicker({
  startDate,
  endDate,
  onDateChange,
  dimension,
  dimensions,
  onDimensionChange,
  dimensionLabel = 'Dimension',
  dateLabel = 'Date Range',
  showDateRange = true,
}: Props) {
  const hasDimensions = !!dimensions && dimensions.length > 0;
  return (
    <div className="space-y-2">
      {/* Date row — suppressed when the parent already renders one. */}
      {showDateRange && (
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Calendar size={16} className="text-[var(--color-text-muted)]" />
          <span className="text-sm font-medium text-[var(--color-text-secondary)]">{dateLabel}</span>
          <InfoTooltip text="Filter every chart on this page by date range. Presets calculate from today's date; custom dates can be entered directly." />
        </div>
        <input
          type="date"
          value={startDate}
          onChange={(e) => onDateChange(e.target.value, endDate)}
          className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
        />
        <span className="text-[var(--color-text-muted)]">to</span>
        <input
          type="date"
          value={endDate}
          onChange={(e) => onDateChange(startDate, e.target.value)}
          className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
        />
        <div className="flex gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => onDateChange(daysAgo(p.days), today())}
              className="px-2.5 py-1 text-xs rounded-full bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-primary)] hover:text-white hover:border-[var(--color-primary)] transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      )}

      {/* Dimension row — only when the page supplies options. */}
      {hasDimensions && (
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <LayoutGrid size={16} className="text-[var(--color-text-muted)]" />
            <span className="text-sm font-medium text-[var(--color-text-secondary)]">{dimensionLabel}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {dimensions!.map((d) => {
              const isActive = d.key === dimension;
              return (
                <button
                  key={d.key}
                  type="button"
                  onClick={() => onDimensionChange?.(d.key)}
                  className={`px-3 py-1 text-xs rounded-full border transition-colors inline-flex items-center gap-1 ${
                    isActive
                      ? 'bg-[var(--color-primary)] border-[var(--color-primary)] text-white'
                      : 'bg-[var(--color-bg-secondary)] border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-primary)] hover:text-white hover:border-[var(--color-primary)]'
                  }`}
                >
                  {d.label}
                  {d.tooltip && <InfoTooltip text={d.tooltip} />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
