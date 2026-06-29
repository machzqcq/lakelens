import InfoTooltip from './InfoTooltip';
import { clsx } from 'clsx';

interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  trend?: number | null;
  icon: React.ReactNode;
  tooltip: string;
  accentColor?: string;
}

export default function KpiCard({ title, value, subtitle, trend, icon, tooltip, accentColor = 'var(--color-primary)' }: KpiCardProps) {
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-2xl p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span style={{ color: accentColor }}>{icon}</span>
          <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">
            {title}
            <InfoTooltip text={tooltip} />
          </h3>
        </div>
        {trend !== undefined && trend !== null && (
          <span className={clsx(
            'text-xs font-semibold px-2 py-0.5 rounded-full',
            trend >= 0 ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
          )}>
            {trend >= 0 ? '+' : ''}{trend.toFixed(1)}%
          </span>
        )}
      </div>
      <p className="text-2xl font-bold text-[var(--color-text-primary)]">{value}</p>
      {subtitle && <p className="text-xs text-[var(--color-text-muted)] mt-1">{subtitle}</p>}
    </div>
  );
}
