/**
 * Executive — board-deck KPIs: adoption, reliability, serverless share, AI uptake.
 *
 * Filter strip at the top: a shared date range (applies to all three charts)
 * plus a per-chart time grain. The grain choices reflect what each chart
 * naturally summarises at — adoption is a monthly KPI but supports week/day
 * for short windows; serverless share is daily by default; reliability is
 * weekly. Each chart's TanStack Query is keyed by (start, end, grain) so
 * changing any picker refetches just that chart.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, CHART_COLORS, LoadingNote } from './shared';
import DateRangeDimensionPicker, { daysAgo, today } from '../../components/DateRangeDimensionPicker';

type Grain = 'day' | 'week' | 'month' | 'quarter' | 'year';

const ADOPTION_GRAINS = [
  { key: 'day',     label: 'Day' },
  { key: 'week',    label: 'Week' },
  { key: 'month',   label: 'Month' },
  { key: 'quarter', label: 'Quarter' },
  { key: 'year',    label: 'Year' },
];

const SERVERLESS_GRAINS = [
  { key: 'day',   label: 'Day' },
  { key: 'week',  label: 'Week' },
  { key: 'month', label: 'Month' },
];

const RELIABILITY_GRAINS = [
  { key: 'day',   label: 'Day' },
  { key: 'week',  label: 'Week' },
  { key: 'month', label: 'Month' },
];


export default function QueryIntelExecutive() {
  // Shared date range across all three charts. Default to "last 6 months"
  // so the page opens with a useful window rather than an unbounded scan.
  const [startDate, setStartDate]   = useState(daysAgo(180));
  const [endDate, setEndDate]       = useState(today());

  // Per-chart grain — each chart has its own picker because the natural
  // bucketing differs (monthly KPI vs daily share vs weekly reliability).
  const [adoptionGrain,    setAdoptionGrain]    = useState<Grain>('month');
  const [serverlessGrain,  setServerlessGrain]  = useState<Grain>('day');
  const [reliabilityGrain, setReliabilityGrain] = useState<Grain>('week');

  const adoption = useQuery({
    queryKey: ['qi-adoption', startDate, endDate, adoptionGrain],
    queryFn: () => qi.adoptionTrend(startDate, endDate, adoptionGrain),
  });
  const sShare = useQuery({
    queryKey: ['qi-eserverless', startDate, endDate, serverlessGrain],
    queryFn: () => qi.executiveServerlessShare(startDate, endDate, serverlessGrain),
  });
  const reliab = useQuery({
    queryKey: ['qi-reliab', startDate, endDate, reliabilityGrain],
    queryFn: () => qi.reliability(startDate, endDate, reliabilityGrain),
  });

  return (
    <QiShell
      title="Executive"
      intro="Adoption KPIs, weekly reliability, and the serverless transition curve — the slide deck for any quarterly review. Filters apply to every chart on the page."
    >
      {/* Page-level filter strip — date range applies to all three charts.
          Each chart has its own per-grain picker below its title. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl px-4 py-3 shadow-sm">
        <DateRangeDimensionPicker
          startDate={startDate}
          endDate={endDate}
          onDateChange={(s, e) => { setStartDate(s); setEndDate(e); }}
          // No page-level dimension — each chart has its own grain picker.
        />
      </div>

      <QiCard
        title="Adoption — distinct users / dashboards / jobs / notebooks / Genie spaces"
        tooltip="One distinct count per period per surface — the broadest read on whether the platform is gaining or losing customers."
      >
        <div className="mb-3">
          <DateRangeDimensionPicker
            startDate={startDate}
            endDate={endDate}
            // Date already shown at the page level; only render the grain row.
            onDateChange={() => undefined}
            showDateRange={false}
            dimension={adoptionGrain}
            dimensions={ADOPTION_GRAINS}
            onDimensionChange={(k) => setAdoptionGrain(k as Grain)}
            dimensionLabel="Time grain"
            dateLabel=""
          />
        </div>
        {adoption.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={adoption.data ?? []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" tick={{ fontSize: 10 }} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="users"        stroke={CHART_COLORS[0]} />
              <Line type="monotone" dataKey="dashboards"   stroke={CHART_COLORS[1]} />
              <Line type="monotone" dataKey="jobs"         stroke={CHART_COLORS[2]} />
              <Line type="monotone" dataKey="notebooks"    stroke={CHART_COLORS[3]} />
              <Line type="monotone" dataKey="genie_spaces" stroke={CHART_COLORS[4]} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard
          title="Serverless vs Warehouse — query share"
          tooltip="Track the migration to Serverless. Stacked = total query volume per period."
        >
          <div className="mb-3">
            <DateRangeDimensionPicker
              startDate={startDate}
              endDate={endDate}
              onDateChange={() => undefined}
              showDateRange={false}
              dimension={serverlessGrain}
              dimensions={SERVERLESS_GRAINS}
              onDimensionChange={(k) => setServerlessGrain(k as Grain)}
              dimensionLabel="Time grain"
              dateLabel=""
            />
          </div>
          {sShare.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={sShare.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" tick={{ fontSize: 10 }} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Area type="monotone" dataKey="serverless" stackId="1" stroke="#06b6d4" fill="#06b6d4" fillOpacity={0.7} />
                <Area type="monotone" dataKey="warehouse"  stackId="1" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.7} />
              </AreaChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard
          title="Success Rate"
          tooltip="FINISHED / total per period. Healthy platforms run >95%."
        >
          <div className="mb-3">
            <DateRangeDimensionPicker
              startDate={startDate}
              endDate={endDate}
              onDateChange={() => undefined}
              showDateRange={false}
              dimension={reliabilityGrain}
              dimensions={RELIABILITY_GRAINS}
              onDimensionChange={(k) => setReliabilityGrain(k as Grain)}
              dimensionLabel="Time grain"
              dateLabel=""
            />
          </div>
          {reliab.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={(reliab.data ?? []).map((r: any) => ({ ...r, pct: Number(r.success_rate) * 100 }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" tick={{ fontSize: 10 }} />
                <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`} domain={[0, 100]} />
                <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                <Line type="monotone" dataKey="pct" stroke="#10b981" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          }
        </QiCard>
      </div>
    </QiShell>
  );
}
