import { describe, it, expect, vi, beforeEach } from 'vitest';
import { attachmentAdapter, ATTACHMENT_ACCEPT } from './attachmentAdapter';

describe('attachmentAdapter', () => {
  it('accept 字段是合法 MIME 列表', () => {
    expect(ATTACHMENT_ACCEPT).toContain('image/png');
    expect(ATTACHMENT_ACCEPT).toContain('application/pdf');
  });

  describe('add', () => {
    it('把 png 转 data URL PendingAttachment', async () => {
      const pngBytes = new Uint8Array([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
        0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
        0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41,
        0x54, 0x78, 0x9c, 0x63, 0x00, 0x01, 0x00, 0x00,
        0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00,
        0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
        0x42, 0x60, 0x82,
      ]);
      const file = new File([pngBytes], 't.png', { type: 'image/png' });
      const att = await attachmentAdapter.add({ file });
      expect(['requires-action', 'running']).toContain(att.status.type);
      expect(att.type).toBe('image');
      expect(att.name).toBe('t.png');
      // SimpleImageAttachmentAdapter 在 add 时不写 content，由 send 时填充
      expect(att.file).toBeDefined();
    });
  });

  describe('send', () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it('上传 data URL 图片到 /api/upload 并返回 URL', async () => {
      const dataUrl =
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
      const mockJson = { url: '/api/files/abc.png', content_type: 'image/png', name: 'x.png' };

      // send 现在不走 fetch(dataUrl).blob()，只走 fetch('/api/upload')
      global.fetch = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => mockJson,
      })) as unknown as typeof fetch;

      const att = {
        id: 'a',
        type: 'image' as const,
        name: 'x.png',
        contentType: 'image/png',
        file: new File([new Uint8Array()], 'x.png', { type: 'image/png' }),
        status: { type: 'requires-action' as const, reason: 'composer-send' as const },
        content: [{ image: dataUrl }],
      };
      const result = await attachmentAdapter.send(att);
      expect(result.status.type).toBe('complete');
      expect((result.content as Array<{ image: string }>)[0].image).toBe('/api/files/abc.png');
    });

    it('上传失败保留原 data URL 仍 complete', async () => {
      global.fetch = vi.fn(async () =>
        ({ ok: false, status: 413, json: async () => ({}) }) as Response,
      );
      const dataUrl = 'data:image/png;base64,iVBORw0KGgo=';
      const att = {
        id: 'b',
        type: 'image' as const,
        name: 'x.png',
        contentType: 'image/png',
        file: new File([new Uint8Array()], 'x.png', { type: 'image/png' }),
        status: { type: 'requires-action' as const, reason: 'composer-send' as const },
        content: [{ image: dataUrl }],
      };
      const result = await attachmentAdapter.send(att);
      // 仍返回 complete，content 保留原 data URL
      expect(result.status.type).toBe('complete');
      expect((result.content as Array<{ image: string }>)[0].image).toBe(dataUrl);
    });

    it('非 data URL 直接 complete', async () => {
      const att = {
        id: 'c',
        type: 'image' as const,
        name: 'x.png',
        contentType: 'image/png',
        file: new File([new Uint8Array()], 'x.png', { type: 'image/png' }),
        status: { type: 'requires-action' as const, reason: 'composer-send' as const },
        content: [{ image: 'https://cdn.example.com/x.png' }],
      };
      const result = await attachmentAdapter.send(att);
      expect(result.status.type).toBe('complete');
    });
  });
});