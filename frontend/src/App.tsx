import { Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { LayoutDashboard, BarChart3, Database, DatabaseZap, MessageSquare, UserCog, Shield, LogOut, Loader2, Brain, ChevronDown, ChevronRight, Flame, BookOpen } from 'lucide-react';
import { lazy, Suspense, useState, type ReactNode } from 'react';

import { AuthProvider, useAuth } from './auth/AuthContext';
import { ThemeProvider } from './theme/ThemeContext';
import ThemeSwitcher from './theme/ThemeSwitcher';
import NotificationsBell from './components/NotificationsBell';
import DemoBanner from './components/DemoBanner';
import ViewModeToggle from './components/ViewModeToggle';
import { useFeatures } from './hooks/useFeatures';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const BillingExplorer = lazy(() => import('./pages/BillingExplorer'));
const CostExplorer = lazy(() => import('./pages/CostExplorer'));
const Trends = lazy(() => import('./pages/Trends'));
const Compute = lazy(() => import('./pages/Compute'));
const Analytics = lazy(() => import('./pages/Analytics'));
const SkuOrigin = lazy(() => import('./pages/SkuOrigin'));
const UserFootprint = lazy(() => import('./pages/UserFootprint'));
const Chatbot = lazy(() => import('./pages/Chatbot'));
const DataManagement = lazy(() => import('./pages/DataManagement'));
const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const VerifyEmail = lazy(() => import('./pages/VerifyEmail'));
const OAuthCallback = lazy(() => import('./pages/OAuthCallback'));
const DatabaseExplorer = lazy(() => import('./pages/admin/DatabaseExplorer'));
const SparkSqlEditor = lazy(() => import('./pages/admin/SparkSqlEditor'));
const AdminUsers = lazy(() => import('./pages/admin/Users'));
const AdminRoles = lazy(() => import('./pages/admin/Roles'));
const QueryIntelOverview = lazy(() => import('./pages/QueryIntel/Overview'));
const QueryIntelPlatform = lazy(() => import('./pages/QueryIntel/Platform'));
const QueryIntelCatalog = lazy(() => import('./pages/QueryIntel/Catalog'));
const QueryIntelFinOps = lazy(() => import('./pages/QueryIntel/FinOps'));
const QueryIntelExecutive = lazy(() => import('./pages/QueryIntel/Executive'));
const QueryIntelDataEng = lazy(() => import('./pages/QueryIntel/DataEng'));
const QueryIntelBI = lazy(() => import('./pages/QueryIntel/BI'));
const QueryIntelDataScience = lazy(() => import('./pages/QueryIntel/DataScience'));
const QueryIntelSecurity = lazy(() => import('./pages/QueryIntel/Security'));
const QueryIntelDevEx = lazy(() => import('./pages/QueryIntel/DevEx'));
const QueryIntelCross = lazy(() => import('./pages/QueryIntel/CrossCutting'));
const MetaExplorer = lazy(() => import('./pages/MetaExplorer'));
const MetaLineageTables = lazy(() => import('./pages/lineage/TableLineagePage'));
const MetaLineageColumns = lazy(() => import('./pages/lineage/ColumnLineagePage'));
const MetaAudit = lazy(() => import('./pages/MetaAudit'));
const MetaNodePool = lazy(() => import('./pages/MetaNodePool'));

const BILLING_SUBITEMS: { path: string; label: string }[] = [
  { path: '/billing-explorer',  label: 'Overview' },
  { path: '/cost-explorer',     label: 'Cost Explorer' },
  { path: '/user-footprint',    label: 'User Footprint' },
  { path: '/trends',            label: 'Trends & Forecast' },
  { path: '/compute',           label: 'Compute Resources' },
  { path: '/sku-origin',        label: 'SKU & Billing Origin' },
  { path: '/analytics',         label: 'Advanced Analytics' },
];

const META_SUBITEMS: { path: string; label: string }[] = [
  { path: '/meta-explorer',                 label: 'Overview' },
  { path: '/meta-explorer/lineage/tables',  label: 'Lineage — Tables' },
  { path: '/meta-explorer/lineage/columns', label: 'Lineage — Columns' },
  { path: '/meta-explorer/audit',           label: 'Audit' },
  { path: '/meta-explorer/node-pool',       label: 'Node Pool' },
];

const QI_SUBITEMS: { path: string; label: string }[] = [
  { path: '/query-intel',              label: 'Overview' },
  { path: '/query-intel/platform',     label: 'Platform / IT Admin' },
  { path: '/query-intel/catalog',      label: 'Catalog Usage' },
  { path: '/query-intel/finops',       label: 'FinOps' },
  { path: '/query-intel/executive',    label: 'Executive' },
  { path: '/query-intel/data-eng',     label: 'Data Engineering' },
  { path: '/query-intel/bi',           label: 'BI / Analytics' },
  { path: '/query-intel/data-science', label: 'Data Science' },
  { path: '/query-intel/security',     label: 'Security & Governance' },
  { path: '/query-intel/devex',        label: 'Developer Experience' },
  { path: '/query-intel/cross-cutting',label: 'Cross-cutting' },
];

interface NavItem {
  path: string;
  label: string;
  icon: typeof LayoutDashboard;
  // Tailwind text-color class applied to the icon when the nav item is NOT
  // the active route. The active route uses white-on-primary regardless.
  iconColor: string;
  adminOnly?: boolean;
  // Optional feature key — when set, the item is hidden if the feature is off.
  featureKey?: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/',                  label: 'Dashboard',         icon: LayoutDashboard, iconColor: 'text-sky-500' },
  { path: '/billing-explorer',  label: 'Billing Explorer',  icon: BarChart3,       iconColor: 'text-blue-500',    featureKey: 'ui.billing_explorer' },
  { path: '/query-intel',       label: 'Query Profiler',    icon: Brain,           iconColor: 'text-purple-500',  featureKey: 'ui.query_profiler' },
  { path: '/meta-explorer',     label: 'Meta Explorer',     icon: BookOpen,        iconColor: 'text-cyan-500',    featureKey: 'ui.meta_explorer' },
  { path: '/chatbot',           label: 'Chatbot',           icon: MessageSquare,   iconColor: 'text-emerald-500', featureKey: 'ui.chatbot' },
  { path: '/data',              label: 'Data Management',   icon: Database,        iconColor: 'text-amber-500',   adminOnly: true, featureKey: 'ui.data_management' },
  { path: '/data/explorer',     label: 'Database Explorer', icon: DatabaseZap,     iconColor: 'text-orange-500',  adminOnly: true, featureKey: 'ui.database_explorer' },
  { path: '/spark-sql',         label: 'Spark SQL Editor',  icon: Flame,           iconColor: 'text-red-500',     adminOnly: true, featureKey: 'ui.spark_sql_editor' },
  { path: '/admin/users',       label: 'Users',             icon: UserCog,         iconColor: 'text-rose-500',    adminOnly: true },
  { path: '/admin/roles',       label: 'Roles',             icon: Shield,          iconColor: 'text-indigo-500',  adminOnly: true },
];

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="animate-spin text-[var(--color-primary)]" size={40} />
    </div>
  );
}

function FullScreenLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-secondary)]">
      <Loader2 className="animate-spin text-[var(--color-primary)]" size={40} />
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === 'loading') return <FullScreenLoader />;
  if (state.status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { state, isAdmin } = useAuth();
  if (state.status === 'loading') return <FullScreenLoader />;
  if (state.status === 'anonymous') return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

/**
 * Block a route when the current user's feature state has `key` disabled.
 * The user's effective features come from their roles (admins/system-user
 * get all). A direct URL hit on a disabled feature redirects to /, matching
 * the sidebar's hide-the-nav-entry behavior.
 */
function RequireFeature({ featureKey, children }: { featureKey: string; children: ReactNode }) {
  const { isEnabled, isLoading } = useFeatures();
  if (isLoading) return <PageLoader />;
  if (!isEnabled(featureKey)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

// Paths that count as "inside" a collapsible group, including the
// group's own root path. Used to auto-expand and to highlight the parent.
const BILLING_GROUP_PATHS = new Set(BILLING_SUBITEMS.map((s) => s.path));
const QI_GROUP_PREFIX = '/query-intel';
const META_GROUP_PREFIX = '/meta-explorer';

function ExpandableGroup({
  Icon,
  iconColor,
  label,
  isOpen,
  onToggle,
  inSection,
  isParentActive,
  items,
  activePath,
  activeClassName,
}: {
  Icon: typeof LayoutDashboard;
  iconColor: string;
  label: string;
  isOpen: boolean;
  onToggle: () => void;
  inSection: boolean;
  isParentActive: boolean;
  items: { path: string; label: string }[];
  activePath: string;
  activeClassName: string;
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        className={`w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isParentActive
            ? 'bg-[var(--color-primary)] text-white shadow-sm'
            : inSection
            ? 'bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]'
            : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]'
        }`}
      >
        <span className="flex items-center gap-3">
          <Icon size={18} className={isParentActive ? 'text-white' : iconColor} />
          {label}
        </span>
        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {isOpen && (
        <div className="mt-1 ml-3 pl-3 border-l border-[var(--color-border)] space-y-0.5">
          {items.map((sub) => (
            <Link
              key={sub.path}
              to={sub.path}
              className={`block px-3 py-1.5 rounded-md text-xs ${
                activePath === sub.path
                  ? activeClassName
                  : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)]'
              }`}
            >
              {sub.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function Sidebar() {
  const location = useLocation();
  const { user, isAdmin, logout } = useAuth();
  const { isEnabled } = useFeatures();

  // 1. Drop admin-only items for non-admins.
  // 2. Drop any item whose feature flag is off for the current user. The
  //    per-user effective feature set is computed server-side from the
  //    union of features across the user's custom roles (admins + plain
  //    'user' get everything). Disabled features are also unreachable by
  //    direct URL — see RequireFeature.
  const visibleItems = NAV_ITEMS.filter(
    (it) => (!it.adminOnly || isAdmin) && (!it.featureKey || isEnabled(it.featureKey)),
  );
  const adminCount = visibleItems.filter((it) => it.adminOnly).length;

  const inBilling = BILLING_GROUP_PATHS.has(location.pathname);
  const inQueryIntel = location.pathname.startsWith(QI_GROUP_PREFIX);
  const inMeta = location.pathname.startsWith(META_GROUP_PREFIX);
  const [billingOpen, setBillingOpen] = useState(inBilling);
  const [qiOpen, setQiOpen] = useState(inQueryIntel);
  const [metaOpen, setMetaOpen] = useState(inMeta);

  return (
    <aside className="w-64 bg-[var(--color-bg-card)] border-r border-[var(--color-border)] flex flex-col">
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--color-primary)] flex items-center justify-center">
            <BarChart3 size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Databricks</h1>
            <p className="text-xs text-[var(--color-text-muted)]">Billing Dashboard</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {visibleItems.map(({ path, label, icon: Icon, iconColor, adminOnly }, i) => {
          const isActive = location.pathname === path;
          const prevAdminOnly = i > 0 ? visibleItems[i - 1].adminOnly : false;
          const showSeparator = adminOnly && !prevAdminOnly && adminCount > 0;

          // Billing Explorer: expandable group covering the legacy sub-views.
          if (path === '/billing-explorer') {
            return (
              <ExpandableGroup
                key={path}
                Icon={Icon}
                iconColor={iconColor}
                label={label}
                isOpen={billingOpen}
                onToggle={() => setBillingOpen((o) => !o)}
                inSection={inBilling}
                isParentActive={isActive}
                items={BILLING_SUBITEMS}
                activePath={location.pathname}
                activeClassName="bg-blue-100 text-blue-700 font-medium"
              />
            );
          }

          // Query Profiler: expandable group with per-department sub-pages.
          if (path === '/query-intel') {
            return (
              <ExpandableGroup
                key={path}
                Icon={Icon}
                iconColor={iconColor}
                label={label}
                isOpen={qiOpen}
                onToggle={() => setQiOpen((o) => !o)}
                inSection={inQueryIntel}
                isParentActive={isActive}
                items={QI_SUBITEMS}
                activePath={location.pathname}
                activeClassName="bg-purple-100 text-purple-700 font-medium"
              />
            );
          }

          // Meta Explorer: expandable group with Overview + Lineage sub-pages.
          if (path === '/meta-explorer') {
            return (
              <ExpandableGroup
                key={path}
                Icon={Icon}
                iconColor={iconColor}
                label={label}
                isOpen={metaOpen}
                onToggle={() => setMetaOpen((o) => !o)}
                inSection={inMeta}
                isParentActive={isActive}
                items={META_SUBITEMS}
                activePath={location.pathname}
                activeClassName="bg-cyan-100 text-cyan-700 font-medium"
              />
            );
          }

          return (
            <div key={path}>
              {showSeparator && (
                <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Admin
                </div>
              )}
              <Link
                to={path}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-[var(--color-primary)] text-white shadow-sm'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]'
                }`}
              >
                <Icon size={18} className={isActive ? 'text-white' : iconColor} />
                {label}
              </Link>
            </div>
          );
        })}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--color-border)]">
        {user && (
          <div className="px-2 mb-2">
            <p className="text-xs text-[var(--color-text-secondary)] truncate" title={user.email}>{user.email}</p>
            <p className="text-[10px] text-[var(--color-text-muted)] truncate">{user.roles.join(', ')}</p>
          </div>
        )}
        <button
          onClick={logout}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
        >
          <LogOut size={14} /> Sign out
        </button>
      </div>
    </aside>
  );
}

function ProtectedShell() {
  const { isEnabled } = useFeatures();
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto bg-[var(--color-bg-secondary)] relative">
        {/* Top-right cluster: view-mode toggle, notifications bell, theme switcher */}
        <div className="absolute top-4 right-6 z-30 flex items-center gap-3">
          {isEnabled('ui.view_mode_toggle') && <ViewModeToggle />}
          {isEnabled('ui.notifications_bell') && <NotificationsBell />}
          {isEnabled('ui.theme_switcher') && <ThemeSwitcher compact />}
        </div>
        {/* Yellow demo-data warning banner — only renders when viewing_data_mode==='demo' */}
        <DemoBanner />
        <div className="p-6">
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/billing-explorer" element={<RequireFeature featureKey="ui.billing_explorer"><BillingExplorer /></RequireFeature>} />
            <Route path="/cost-explorer"    element={<RequireFeature featureKey="ui.billing_explorer"><CostExplorer /></RequireFeature>} />
            <Route path="/user-footprint"   element={<RequireFeature featureKey="ui.billing_explorer"><UserFootprint /></RequireFeature>} />
            <Route path="/trends"           element={<RequireFeature featureKey="ui.billing_explorer"><Trends /></RequireFeature>} />
            <Route path="/compute"          element={<RequireFeature featureKey="ui.billing_explorer"><Compute /></RequireFeature>} />
            <Route path="/analytics"        element={<RequireFeature featureKey="ui.billing_explorer"><Analytics /></RequireFeature>} />
            <Route path="/sku-origin"       element={<RequireFeature featureKey="ui.billing_explorer"><SkuOrigin /></RequireFeature>} />
            <Route path="/query-intel"                element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelOverview /></RequireFeature>} />
            <Route path="/query-intel/platform"       element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelPlatform /></RequireFeature>} />
            <Route path="/query-intel/catalog"        element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelCatalog /></RequireFeature>} />
            <Route path="/query-intel/finops"         element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelFinOps /></RequireFeature>} />
            <Route path="/query-intel/executive"      element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelExecutive /></RequireFeature>} />
            <Route path="/query-intel/data-eng"       element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelDataEng /></RequireFeature>} />
            <Route path="/query-intel/bi"             element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelBI /></RequireFeature>} />
            <Route path="/query-intel/data-science"   element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelDataScience /></RequireFeature>} />
            <Route path="/query-intel/security"       element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelSecurity /></RequireFeature>} />
            <Route path="/query-intel/devex"          element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelDevEx /></RequireFeature>} />
            <Route path="/query-intel/cross-cutting"  element={<RequireFeature featureKey="ui.query_profiler"><QueryIntelCross /></RequireFeature>} />
            <Route path="/meta-explorer" element={<RequireFeature featureKey="ui.meta_explorer"><MetaExplorer /></RequireFeature>} />
            <Route path="/meta-explorer/lineage" element={<Navigate to="/meta-explorer/lineage/tables" replace />} />
            <Route path="/meta-explorer/lineage/tables"  element={<RequireFeature featureKey="ui.meta_explorer"><MetaLineageTables /></RequireFeature>} />
            <Route path="/meta-explorer/lineage/columns" element={<RequireFeature featureKey="ui.meta_explorer"><MetaLineageColumns /></RequireFeature>} />
            <Route path="/meta-explorer/audit" element={<RequireFeature featureKey="ui.meta_explorer"><MetaAudit /></RequireFeature>} />
            <Route path="/meta-explorer/node-pool" element={<RequireFeature featureKey="ui.meta_explorer"><MetaNodePool /></RequireFeature>} />
            <Route path="/chatbot"       element={<RequireFeature featureKey="ui.chatbot"><Chatbot /></RequireFeature>} />
            <Route path="/data"          element={<RequireAdmin><RequireFeature featureKey="ui.data_management"><DataManagement /></RequireFeature></RequireAdmin>} />
            <Route path="/data/explorer" element={<RequireAdmin><RequireFeature featureKey="ui.database_explorer"><DatabaseExplorer /></RequireFeature></RequireAdmin>} />
            <Route path="/spark-sql"     element={<RequireAdmin><RequireFeature featureKey="ui.spark_sql_editor"><SparkSqlEditor /></RequireFeature></RequireAdmin>} />
            <Route path="/admin/users"   element={<RequireAdmin><AdminUsers /></RequireAdmin>} />
            <Route path="/admin/roles"   element={<RequireAdmin><AdminRoles /></RequireAdmin>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Suspense fallback={<FullScreenLoader />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/verify-email" element={<VerifyEmail />} />
            <Route path="/oauth/callback" element={<OAuthCallback />} />
            <Route path="*" element={<RequireAuth><ProtectedShell /></RequireAuth>} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </ThemeProvider>
  );
}
