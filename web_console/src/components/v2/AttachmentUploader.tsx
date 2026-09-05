/**
 * v2.0 slim — AttachmentUploader
 *
 * 复用 lib/attachmentAdapter 上传附件。
 */
import { useRef, useState } from 'react';
import { api } from '@/lib/api';

export function AttachmentUploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      await api.uploadAttachment(fd);
    } catch (e: any) {
      setErr(e?.message ?? 'upload failed');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        onChange={onPick}
        disabled={busy}
        className="block w-full text-xs"
        data-testid="attachment-input"
      />
      {err && <p className="text-xs text-red-500 mt-1">{err}</p>}
      {busy && <p className="text-xs text-slate-500 mt-1">上传中…</p>}
    </div>
  );
}