/**
 * fileUpload — v2.1 多模态文件上传工具
 *
 * 职责：
 *  - 调用 /api/files/upload（multipart）
 *  - 把响应归一化成前端 PendingFile（带 file_id / url / 解析文本）
 *  - 提供 uploadFiles（并发批量） + 类型守卫
 */
import { api } from './api';

export interface UploadedFile {
  file_id: string;
  file_name: string;
  file_type: string;
  content_type: string;
  size: number;
  url: string;
  /** 后端解析后的文本（用于上下文注入；空表示不注入） */
  parsed_text: string;
  parsed_kind: string;
}

const ACCEPT_MIME_PREFIXES = [
  'image/',
  'application/pdf',
  'text/',
  'application/json',
];

export function isAcceptedFile(file: File): boolean {
  const ct = (file.type || '').toLowerCase();
  if (!ct) return true; // 没 MIME 的也尝试（部分系统 clipboard 给的 File 没 type）
  return ACCEPT_MIME_PREFIXES.some((p) => ct.startsWith(p)) || ct === 'application/json';
}

export async function uploadOneFile(file: File): Promise<UploadedFile> {
  const fd = new FormData();
  fd.append('file', file, file.name || 'file');
  const res = await fetch('/api/files/upload', {
    method: 'POST',
    body: fd,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      msg = j?.detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  const data = (await res.json()) as {
    file_id?: string;
    id?: string;
    file_name?: string;
    name?: string;
    file_type?: string;
    content_type?: string;
    size?: number;
    url?: string;
    parsed?: { text?: string; kind?: string };
  };
  return {
    file_id: data.file_id || data.id || '',
    file_name: data.file_name || data.name || file.name,
    file_type: data.file_type || '',
    content_type: data.content_type || file.type || '',
    size: typeof data.size === 'number' ? data.size : file.size,
    url: data.url || '',
    parsed_text: data.parsed?.text || '',
    parsed_kind: data.parsed?.kind || 'unknown',
  };
}

export async function uploadFiles(
  files: File[],
  options: { concurrency?: number } = {},
): Promise<UploadedFile[]> {
  const conc = Math.max(1, options.concurrency ?? 3);
  const out: UploadedFile[] = [];
  // 简单并发池
  const queue = files.slice();
  const workers: Array<Promise<void>> = [];
  for (let i = 0; i < conc; i++) {
    workers.push(
      (async () => {
        while (queue.length > 0) {
          const f = queue.shift();
          if (!f) break;
          try {
            const up = await uploadOneFile(f);
            out.push(up);
          } catch (e) {
            // 单个失败不阻塞其它；记 console 由 UI 决定是否 toast
            // eslint-disable-next-line no-console
            console.warn('[fileUpload] upload failed', f.name, e);
          }
        }
      })(),
    );
  }
  await Promise.all(workers);
  return out;
}

// 给 vitest 留 re-export
export const _fileUploadHelpers = { isAcceptedFile, ACCEPT_MIME_PREFIXES };
