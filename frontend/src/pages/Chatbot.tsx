import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { MessageSquare, Send, User, Bot, AlertCircle, Loader2, Code2, FileText, Copy, Check, FileSpreadsheet, Download } from 'lucide-react';

import {
  fetchChatModels,
  postChatAsk,
  downloadChatResults,
  type ChatAskResponse,
  type LlmCall,
} from '../api/client';

type ChatTurn =
  | { role: 'user'; text: string; ts: number }
  | { role: 'assistant'; response: ChatAskResponse; ts: number }
  | { role: 'error'; text: string; ts: number };

const DEFAULT_PROVIDER = 'google';
const DEFAULT_MODEL = 'gemini-2.0-flash';

function ResultTable({ columns, rows, truncated }: { columns: string[]; rows: Record<string, unknown>[]; truncated: boolean }) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)] italic py-2">Query returned no rows.</p>;
  }
  return (
    <div className="overflow-x-auto border border-[var(--color-border)] rounded-lg">
      <table className="w-full text-xs">
        <thead className="bg-[var(--color-bg-secondary)]">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-semibold text-[var(--color-text-muted)] whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-[var(--color-bg-secondary)]/40'}>
              {columns.map((c) => {
                const v = r[c];
                const display =
                  v === null || v === undefined
                    ? ''
                    : typeof v === 'object'
                    ? JSON.stringify(v)
                    : String(v);
                return (
                  <td key={c} className="px-3 py-1.5 text-[var(--color-text-primary)] font-mono whitespace-nowrap">
                    {display}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <p className="text-[10px] text-[var(--color-text-muted)] px-3 py-1.5 border-t border-[var(--color-border)]">
          Showing first 200 rows.
        </p>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
      title="Copy to clipboard"
      className="ml-2 p-1 rounded text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors"
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
    </button>
  );
}

function CallSubsection({ call, index }: { call: LlmCall; index: number }) {
  const sysLen = call.system_prompt?.length ?? 0;
  const userLen = call.user_message?.length ?? 0;
  return (
    <div className="border border-[var(--color-border)] rounded-lg p-3 bg-white">
      <div className="flex items-center gap-2 mb-2">
        <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase rounded bg-[var(--color-primary)] text-white">
          #{index + 1}
        </span>
        <span className="text-[11px] font-semibold text-[var(--color-text-primary)] font-mono">{call.name}</span>
        <span className="text-[10px] text-[var(--color-text-muted)] ml-auto">
          {call.elapsed_seconds.toFixed(3)}s · system {sysLen.toLocaleString()} chars · user {userLen.toLocaleString()} chars
        </span>
      </div>
      <div className="space-y-2">
        <div>
          <div className="flex items-center mb-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--color-text-muted)]">System prompt</span>
            <CopyButton text={call.system_prompt} />
          </div>
          <pre className="p-3 bg-[#0d1117] text-[#c9d1d9] rounded-lg overflow-auto text-[10px] leading-snug font-mono max-h-[220px] whitespace-pre-wrap break-words">
            {call.system_prompt}
          </pre>
        </div>
        <div>
          <div className="flex items-center mb-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--color-text-muted)]">User message</span>
            <CopyButton text={call.user_message} />
          </div>
          <pre className="p-3 bg-[#0d1117] text-[#c9d1d9] rounded-lg overflow-auto text-[10px] leading-snug font-mono max-h-[220px] whitespace-pre-wrap break-words">
            {call.user_message}
          </pre>
        </div>
        <div>
          <div className="flex items-center mb-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--color-text-muted)]">Raw LLM response</span>
            <CopyButton text={call.raw_response} />
          </div>
          <pre className="p-3 bg-[#0d1117] text-[#c9d1d9] rounded-lg overflow-auto text-[10px] leading-snug font-mono max-h-[220px] whitespace-pre-wrap break-words">
            {call.raw_response}
          </pre>
        </div>
      </div>
    </div>
  );
}

function LlmCallDisclosure({ response }: { response: ChatAskResponse }) {
  // Fall back to legacy single-call shape if llm_calls absent (older backend)
  const calls: LlmCall[] = response.llm_calls && response.llm_calls.length > 0
    ? response.llm_calls
    : [{
        name: 'sql_generation',
        system_prompt: response.system_prompt,
        user_message: response.user_message,
        raw_response: response.raw_llm_response,
        elapsed_seconds: response.elapsed_seconds,
      }];
  const totalElapsed = response.total_elapsed_seconds ?? response.elapsed_seconds;

  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] select-none flex items-center gap-1.5">
        <FileText size={12} /> LLM call details
        <span className="text-[10px] text-[var(--color-text-muted)] ml-1">
          ({response.provider} / {response.model} · {calls.length} call{calls.length !== 1 ? 's' : ''} · total {totalElapsed.toFixed(2)}s)
        </span>
      </summary>
      <div className="mt-2 space-y-3 border border-[var(--color-border)] rounded-lg p-3 bg-[var(--color-bg-secondary)]/50">
        <div>
          <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--color-text-muted)]">Request metadata</span>
          <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] font-mono text-[var(--color-text-secondary)]">
            <div><span className="text-[var(--color-text-muted)]">provider:</span> {response.provider}</div>
            <div><span className="text-[var(--color-text-muted)]">model:</span> {response.model}</div>
            <div><span className="text-[var(--color-text-muted)]">total_elapsed:</span> {totalElapsed.toFixed(3)}s</div>
            <div><span className="text-[var(--color-text-muted)]">rows:</span> {response.row_count}</div>
          </div>
        </div>
        {calls.map((c, i) => (
          <CallSubsection key={i} call={c} index={i} />
        ))}
      </div>
    </details>
  );
}

function DownloadButtons({ sql, userMessage }: { sql: string; userMessage: string }) {
  const [busy, setBusy] = useState<'csv' | 'xlsx' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stem = userMessage
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40) || 'chatbot-result';

  async function handle(format: 'csv' | 'xlsx') {
    setBusy(format);
    setError(null);
    try {
      await downloadChatResults(sql, format, stem);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => handle('csv')}
        disabled={busy !== null}
        title="Download full result as CSV"
        className="flex items-center gap-1 p-1.5 rounded text-[var(--color-text-muted)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-50 transition-colors"
      >
        {busy === 'csv' ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
        <span className="text-[10px] font-semibold uppercase">CSV</span>
      </button>
      <button
        type="button"
        onClick={() => handle('xlsx')}
        disabled={busy !== null}
        title="Download full result as Excel"
        className="flex items-center gap-1 p-1.5 rounded text-[var(--color-text-muted)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-50 transition-colors"
      >
        {busy === 'xlsx' ? <Loader2 size={12} className="animate-spin" /> : <FileSpreadsheet size={12} />}
        <span className="text-[10px] font-semibold uppercase">Excel</span>
      </button>
      {error && (
        <span className="text-[10px] text-red-600 ml-1" title={error}>
          download failed
        </span>
      )}
    </div>
  );
}

function AssistantTurn({ response }: { response: ChatAskResponse }) {
  const hasError = !!response.error;
  return (
    <div className="space-y-3">
      {/* Error banner — shown when the SQL was rejected OR execution failed.
          The rest of the turn (SQL preview + LLM call disclosure) still
          renders so the user can see exactly what the model produced. */}
      {hasError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertCircle size={14} className="text-red-600 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-red-700">Query was not executed</p>
            <p className="text-xs text-red-700 leading-relaxed mt-0.5 whitespace-pre-wrap">
              {response.error}
            </p>
          </div>
        </div>
      )}
      {response.explanation && (
        <p className="text-sm text-[var(--color-text-primary)] leading-relaxed">
          {response.explanation}
        </p>
      )}
      <details className="text-xs" open={!response.explanation || hasError}>
        <summary className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] select-none flex items-center gap-1.5">
          <Code2 size={12} /> {hasError ? 'Rejected SQL (what the LLM produced)' : 'Generated SQL'}
          <CopyButton text={response.sql} />
        </summary>
        <pre className="mt-2 p-3 bg-[#0d1117] text-[#c9d1d9] rounded-lg overflow-x-auto text-[11px] leading-relaxed font-mono">
          {response.sql}
        </pre>
      </details>
      {!hasError && (
        <>
          <ResultTable columns={response.columns} rows={response.rows} truncated={response.truncated} />
          <div className="flex items-center justify-between flex-wrap gap-2">
            <p className="text-[10px] text-[var(--color-text-muted)]">
              {response.row_count} row{response.row_count !== 1 ? 's' : ''} returned
              {response.truncated ? ' (showing first 200 in preview — use Download for full set).' : '.'}
            </p>
            {response.row_count > 0 && (
              <DownloadButtons sql={response.sql} userMessage={response.user_message} />
            )}
          </div>
        </>
      )}
      <LlmCallDisclosure response={response} />
    </div>
  );
}

export default function Chatbot() {
  const [provider, setProvider] = useState(DEFAULT_PROVIDER);
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [explain, setExplain] = useState(true);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Models query is intentionally low-priority + heavily cached:
  //  - The backend probes every LLM provider's API (slow). It now runs in a
  //    thread pool with a TTL cache, so other endpoints aren't blocked.
  //  - On the client we keep results fresh for 10 minutes and do NOT
  //    refetch on window-focus or remount, so navigating away and back
  //    doesn't re-trigger a slow round-trip.
  //  - If it's still loading, the rest of the chat UI renders immediately
  //    and the dropdowns just show the default provider/model placeholder.
  const modelsQ = useQuery({
    queryKey: ['chatModels'],
    queryFn: fetchChatModels,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  });

  const providers = useMemo(() => Object.keys(modelsQ.data?.models ?? {}).sort(), [modelsQ.data]);
  const modelsForProvider = modelsQ.data?.models[provider] ?? [];

  // Default model selection when models arrive
  useEffect(() => {
    if (modelsQ.data && !modelsForProvider.includes(model)) {
      if (modelsForProvider.length > 0) setModel(modelsForProvider[0]);
    }
  }, [modelsQ.data, provider, modelsForProvider, model]);

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [history]);

  const askMutation = useMutation({
    mutationFn: postChatAsk,
    onSuccess: (data) => {
      setHistory((h) => [...h, { role: 'assistant', response: data, ts: Date.now() }]);
    },
    onError: (err: Error) => {
      setHistory((h) => [...h, { role: 'error', text: err.message, ts: Date.now() }]);
    },
  });

  function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || askMutation.isPending) return;
    setHistory((h) => [...h, { role: 'user', text, ts: Date.now() }]);
    setInput('');
    askMutation.mutate({ message: text, provider, model, explain });
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] max-w-[1100px] mx-auto">
      {/* Header */}
      <div className="mb-4 shrink-0">
        <div className="flex items-center gap-3 mb-2">
          <MessageSquare size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Chatbot</h1>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3 text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Ask questions in plain English. The LLM generates DuckDB SQL against the parquet
          files in <code>data/</code> using the metadata workbook as context. Try things like
          "Top 10 users by cost in the last 30 days" or "Which clusters used Photon?".
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--color-text-muted)]">Provider:</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={modelsQ.isLoading}
            className="text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 min-w-[140px]"
          >
            {providers.length === 0 && <option value={provider}>{provider}</option>}
            {providers.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--color-text-muted)]">Model:</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={modelsQ.isLoading || modelsForProvider.length === 0}
            className="text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 min-w-[260px]"
          >
            {modelsForProvider.length === 0 && <option value={model}>{model}</option>}
            {modelsForProvider.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)] cursor-pointer">
          <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />
          Explain results
        </label>
        {modelsQ.isError && (
          <span className="text-xs text-red-600 flex items-center gap-1">
            <AlertCircle size={12} /> Failed to load model list (using defaults)
          </span>
        )}
      </div>

      {/* Conversation */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-white border border-[var(--color-border)] rounded-2xl p-5 space-y-5 mb-3"
      >
        {history.length === 0 && !askMutation.isPending && (
          <div className="text-center text-xs text-[var(--color-text-muted)] py-12">
            Start a conversation by asking a question below.
          </div>
        )}
        {history.map((turn, i) => (
          <div key={i} className="flex gap-3">
            <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center"
              style={{
                backgroundColor:
                  turn.role === 'user' ? 'var(--color-primary)' :
                  turn.role === 'error' ? '#fee2e2' : 'var(--color-bg-secondary)',
              }}>
              {turn.role === 'user' ? <User size={14} className="text-white" /> :
               turn.role === 'error' ? <AlertCircle size={14} className="text-red-700" /> :
               <Bot size={14} className="text-[var(--color-text-secondary)]" />}
            </div>
            <div className="flex-1 min-w-0">
              {turn.role === 'user' ? (
                <p className="text-sm text-[var(--color-text-primary)]">{turn.text}</p>
              ) : turn.role === 'error' ? (
                <p className="text-sm text-red-700">{turn.text}</p>
              ) : (
                <AssistantTurn response={turn.response} />
              )}
            </div>
          </div>
        ))}
        {askMutation.isPending && (
          <div className="flex gap-3">
            <div className="shrink-0 w-7 h-7 rounded-full bg-[var(--color-bg-secondary)] flex items-center justify-center">
              <Loader2 size={14} className="text-[var(--color-text-secondary)] animate-spin" />
            </div>
            <p className="text-sm text-[var(--color-text-muted)] italic">Thinking...</p>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex gap-2 shrink-0">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about your billing data..."
          disabled={askMutation.isPending}
          className="flex-1 bg-white border border-[var(--color-border)] rounded-lg px-4 py-2.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
        />
        <button
          type="submit"
          disabled={askMutation.isPending || !input.trim()}
          className="px-4 py-2.5 rounded-lg bg-[var(--color-primary)] text-white text-sm font-medium flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--color-primary)]/90 transition-colors"
        >
          {askMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Ask
        </button>
      </form>
    </div>
  );
}
