import {
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
} from '@assistant-ui/react';
import { useChatStore } from '@/stores/chatStore';
import type { PersistedAttachment } from '@/types/api';

const ACCEPTED = 'image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown';

/**
 * 本地附件适配器：上传到服务端 /api/upload，返回带 url 的 CompleteAttachment。
 * 后端把文件落到 ai_agent/uploads/，并通过 /api/files/{name} 提供访问。
 */
function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [meta = '', b64 = ''] = dataUrl.split(',');
  const mimeMatch = /data:([^;]+)(;base64)?/i.exec(meta);
  const mime = mimeMatch?.[1] || 'application/octet-stream';
  const isBase64 = /;base64/i.test(meta);
  const bin = isBase64
    ? atob(b64)
    : decodeURIComponent(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

const inner = new SimpleImageAttachmentAdapter();

const localUploadAdapter = {
  accept: ACCEPTED,
  add: (state: { file: File }) => inner.add(state),
  send: async (att: Parameters<typeof inner.send>[0]) => {
    const part = att.content?.find((c: { type?: string; image?: string }) =>
      typeof c?.image === 'string',
    ) as { image: string } | undefined;
    let nextContent = att.content ?? [];
    if (part && part.image.startsWith('data:')) {
      try {
        const blob = dataUrlToBlob(part.image);
        const fileName = att.name ?? 'image.png';
        const fd = new FormData();
        fd.append(
          'file',
          new File([blob], fileName, {
            type: blob.type || att.contentType || 'image/png',
          }),
        );
        const res = await fetch('/api/upload', { method: 'POST', body: fd });
        if (res.ok) {
          const json = (await res.json()) as {
            url: string;
            name?: string;
            content_type?: string;
            size?: number;
            id?: string;
          };
          nextContent = [{ image: json.url }] as never;
          // 写入 chatStore：持久化到 localStorage
          try {
            const persisted: PersistedAttachment = {
              id: json.id ?? att.id ?? crypto.randomUUID?.() ?? `${Date.now()}`,
              name: json.name ?? fileName,
              url: json.url,
              contentType: json.content_type ?? blob.type ?? 'image/png',
              size: json.size ?? blob.size,
              uploadedAt: Date.now(),
            };
            const sessionId = useChatStore.getState().activeSessionId;
            useChatStore.getState().addAttachment(sessionId, persisted);
          } catch {
            /* store 写入失败不影响主流程 */
          }
        }
        // 失败：保留原 data URL（前端仍可展示，但服务端未持久化）
      } catch {
        // 静默失败：保留原 content
      }
    }
    return {
      ...att,
      status: { type: 'complete' as const },
      content: nextContent,
    };
  },
  remove: () => inner.remove(),
};

export const attachmentAdapter = new CompositeAttachmentAdapter([localUploadAdapter]);
export const ATTACHMENT_ACCEPT = ACCEPTED;