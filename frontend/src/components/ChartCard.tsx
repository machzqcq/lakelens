import { Loader2, FileText, FileSpreadsheet } from 'lucide-react';
import InfoTooltip from './InfoTooltip';
import { exportToCsv, exportToXlsx, type ExportRow } from '../utils/export';

interface ChartCardProps {
  title: string;
  tooltip: string;
  children: React.ReactNode;
  isLoading?: boolean;
  className?: string;
  /** Rows powering the chart. When provided, CSV / XLSX download buttons
   *  appear in the card header. Pass a function for lazily-computed data. */
  exportRows?: ExportRow[] | (() => ExportRow[]);
  /** Filename stem (no extension). Defaults to the chart title. */
  exportFilename?: string;
}

export default function ChartCard({
  title,
  tooltip,
  children,
  isLoading,
  className = '',
  exportRows,
  exportFilename,
}: ChartCardProps) {
  const resolveRows = (): ExportRow[] =>
    typeof exportRows === 'function' ? exportRows() : (exportRows ?? []);

  const fname = exportFilename || title;

  const showExports = exportRows !== undefined;

  return (
    <div className={`bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-2xl p-5 shadow-sm ${className}`}>
      <div className="flex items-start justify-between mb-4 gap-3">
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
          {title}
          <InfoTooltip text={tooltip} />
        </h3>
        {showExports && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => exportToCsv(fname, resolveRows())}
              title="Download CSV"
              className="p-1.5 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg-secondary)] transition-colors"
            >
              <FileText size={14} />
            </button>
            <button
              onClick={() => exportToXlsx(fname, resolveRows(), title.slice(0, 31))}
              title="Download Excel"
              className="p-1.5 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg-secondary)] transition-colors"
            >
              <FileSpreadsheet size={14} />
            </button>
          </div>
        )}
      </div>
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="animate-spin text-[var(--color-primary)]" size={32} />
        </div>
      ) : children}
    </div>
  );
}
