/**
 * Dashboard — the landing page after sign-in. A hub of large cards linking
 * to each of the major product areas. The detailed billing charts/KPIs that
 * previously lived here have moved to `/billing-explorer` (BillingExplorer.tsx).
 */
import { Link } from 'react-router-dom';
import { BarChart3, Brain, BookOpen, MessageSquare, ArrowRight, type LucideIcon } from 'lucide-react';

interface HubCard {
  to: string;
  title: string;
  description: string;
  icon: LucideIcon;
  accent: string;         // tailwind text color class for the icon tile
  bgAccent: string;       // tailwind background tint for the icon tile
}

const CARDS: HubCard[] = [
  {
    to: '/billing-explorer',
    title: 'Billing Explorer',
    description:
      'Estimated spend across SKUs, billing origins, workspaces, and time. Drill into the Cost Explorer, User Footprint, Trends & Forecast, Compute Resources, SKU & Billing Origin, and Advanced Analytics sub-views.',
    icon: BarChart3,
    accent: 'text-[var(--color-primary)]',
    bgAccent: 'bg-blue-50',
  },
  {
    to: '/query-intel',
    title: 'Query Profiler',
    description:
      'Parsed view of every row of query_history — tables and columns touched, error categories, source applications, expensive statements. Departmental scenarios under sub-routes.',
    icon: Brain,
    accent: 'text-purple-600',
    bgAccent: 'bg-purple-50',
  },
  {
    to: '/meta-explorer',
    title: 'Meta Explorer',
    description:
      'Browse the Unity Catalog snapshot — catalogs, databases, tables, columns, types, owners, comments. Search across the whole tree and export catalogs / tables / columns to CSV or XLSX.',
    icon: BookOpen,
    accent: 'text-cyan-600',
    bgAccent: 'bg-cyan-50',
  },
  {
    to: '/chatbot',
    title: 'Chatbot',
    description:
      'Natural-language Q&A over the operational warehouse. Schema-aware SQL generation guarded by a parser, with results rendered as tables and charts.',
    icon: MessageSquare,
    accent: 'text-emerald-600',
    bgAccent: 'bg-emerald-50',
  },
];

export default function Dashboard() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Dashboard</h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Pick where to start. Each card opens one of the four primary surfaces of the app.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        {CARDS.map(({ to, title, description, icon: Icon, accent, bgAccent }) => (
          <Link
            key={to}
            to={to}
            className="group bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm hover:shadow-md hover:border-[var(--color-primary)] transition-all flex flex-col"
          >
            <div className="flex items-start gap-4">
              <div className={`${bgAccent} ${accent} w-12 h-12 rounded-xl flex items-center justify-center shrink-0`}>
                <Icon size={22} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h2>
                  <ArrowRight
                    size={16}
                    className="text-[var(--color-text-muted)] group-hover:text-[var(--color-primary)] group-hover:translate-x-0.5 transition-all"
                  />
                </div>
                <p className="text-sm text-[var(--color-text-secondary)] mt-2 leading-relaxed">
                  {description}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
