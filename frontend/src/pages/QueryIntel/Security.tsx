/**
 * Security & Governance — permission denials, off-hours, bulk export, grant/revoke audit, driver versions.
 */
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtBytes, LoadingNote } from './shared';

export default function QueryIntelSecurity() {
  const denied = useQuery({ queryKey: ['qi-denied'], queryFn: () => qi.permissionDenied(50) });
  const offhrs = useQuery({ queryKey: ['qi-offhrs'], queryFn: () => qi.offHoursPii(30) });
  const bulk = useQuery({ queryKey: ['qi-bulk'], queryFn: () => qi.bulkExport(30) });
  const grants = useQuery({ queryKey: ['qi-grants'], queryFn: () => qi.grantRevoke(30) });
  const drivers = useQuery({ queryKey: ['qi-drivers'], queryFn: () => qi.driverVersions() });
  const delegated = useQuery({ queryKey: ['qi-delegated'], queryFn: () => qi.delegatedExecution(30) });

  return (
    <QiShell
      title="Security & Governance"
      intro="Permission denials, off-hours activity, bulk-export sessions, GRANT/REVOKE history, and connector-version posture."
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="Permission-Denied Trail"
          tooltip="Who got denied access to what, how often. Build the Unity Catalog backlog from this.">
          {denied.isLoading ? <LoadingNote /> :
            <MiniTable rows={denied.data ?? []} columns={[
              { key: 'user', label: 'User' },
              { key: 'referenced_object', label: 'Object' },
              { key: 'denials', label: 'Denials', align: 'right', render: (v) => fmtInt.format(v) },
            ]} />
          }
        </QiCard>

        <QiCard title="Off-Hours Human Activity"
          tooltip="Humans (not service principals) running queries outside business hours. First filter for insider-risk review.">
          {offhrs.isLoading ? <LoadingNote /> :
            <MiniTable rows={offhrs.data ?? []} columns={[
              { key: 'user', label: 'User' },
              { key: 'off_hour_queries', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
              { key: 'read_bytes', label: 'Read', align: 'right', render: (v) => fmtBytes(v) },
            ]} />
          }
        </QiCard>

        <QiCard title="Bulk-Export Sessions (>5 GB)"
          tooltip="Sessions that read >5 GB. Confirm intent — may be legit batch exports, may be exfil.">
          {bulk.isLoading ? <LoadingNote /> :
            <MiniTable rows={bulk.data ?? []} columns={[
              { key: 'user', label: 'User' },
              { key: 'queries', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
              { key: 'read_bytes', label: 'Read', align: 'right', render: (v) => fmtBytes(v) },
              { key: 'read_rows', label: 'Rows', align: 'right', render: (v) => fmtInt.format(v ?? 0) },
            ]} />
          }
        </QiCard>

        <QiCard title="GRANT / REVOKE Audit"
          tooltip="Permission changes. Reconstruct who touched ACLs and when.">
          {grants.isLoading ? <LoadingNote /> :
            <MiniTable rows={grants.data ?? []} columns={[
              { key: 'executed_by', label: 'User' },
              { key: 'start_time', label: 'Time', render: (v) => (v ? new Date(v).toLocaleString() : '—') },
              { key: 'statement_text_excerpt', label: 'Statement',
                render: (v) => <span className="font-mono text-xs">{(v || '').slice(0, 80)}…</span> },
            ]} emptyMessage="No GRANT/REVOKE statements." />
          }
        </QiCard>

        <QiCard title="Connector / Driver Footprint"
          tooltip="Driver family + version distribution. Feeds CVE-patch backlog.">
          {drivers.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={(drivers.data ?? []).slice(0, 15)} layout="vertical" margin={{ left: 140 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="version" width={150} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="statements" fill="#ef4444" />
              </BarChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard title="Delegated / On-Behalf-Of Execution"
          tooltip="executed_by != executed_as. Useful for OAuth + service-principal audits.">
          {delegated.isLoading ? <LoadingNote /> :
            <MiniTable rows={delegated.data ?? []} columns={[
              { key: 'executed_by', label: 'Originator' },
              { key: 'executed_as', label: 'Executed As' },
              { key: 'statements', label: 'Statements', align: 'right', render: (v) => fmtInt.format(v) },
            ]} emptyMessage="No delegated executions detected." />
          }
        </QiCard>
      </div>
    </QiShell>
  );
}
