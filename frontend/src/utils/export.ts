/**
 * Tabular export helpers for chart data.
 *
 * Both functions take rows of `Record<string, primitive>` and trigger a
 * browser download. CSV is built inline; XLSX delegates to SheetJS.
 */

import * as XLSX from 'xlsx';

export type ExportRow = Record<string, string | number | boolean | null | undefined>;

/** Sanitize a filename: lowercase, kebab-case, no extension. */
function safeName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'export';
}

function timestamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
}

/** Escape a single CSV field per RFC 4180. */
function csvField(v: unknown): string {
  if (v === null || v === undefined) return '';
  const s = typeof v === 'string' ? v : String(v);
  // Quote if contains comma, quote, or newline
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke on next tick so the click has a chance to start the download
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function exportToCsv(filename: string, rows: ExportRow[]): void {
  if (rows.length === 0) {
    triggerDownload(new Blob([''], { type: 'text/csv;charset=utf-8' }), `${safeName(filename)}-${timestamp()}.csv`);
    return;
  }
  // Use the union of keys so sparse rows still align
  const headerSet = new Set<string>();
  for (const r of rows) for (const k of Object.keys(r)) headerSet.add(k);
  const headers = [...headerSet];

  const lines = [headers.map(csvField).join(',')];
  for (const r of rows) {
    lines.push(headers.map((h) => csvField(r[h])).join(','));
  }
  // Prepend BOM so Excel recognizes UTF-8
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  triggerDownload(blob, `${safeName(filename)}-${timestamp()}.csv`);
}

export function exportToXlsx(filename: string, rows: ExportRow[], sheetName: string = 'Sheet1'): void {
  const ws = XLSX.utils.json_to_sheet(rows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName.slice(0, 31) || 'Sheet1');
  // writeFile triggers the download via internal blob mechanics
  XLSX.writeFile(wb, `${safeName(filename)}-${timestamp()}.xlsx`);
}
