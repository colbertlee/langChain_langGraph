/**
 * v2.0 slim — ChatPage
 *
 * 聚合：流式事件渲染 + 工具调用时间线 + 附件上传。
 * 复用了 assistant-ui 的 Thread 组件（components/assistant-ui/thread.tsx），
 * 不重复实现流式逻辑；这里只挂上"工具调用时间线"与"附件上传"。
 */
import { Thread } from '@/components/assistant-ui/thread';
import { ToolCallTimeline } from '@/components/v2/ToolCallTimeline';
import { AttachmentUploader } from '@/components/v2/AttachmentUploader';

export function ChatPage() {
  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0">
        <Thread />
      </div>
      <aside className="w-80 border-l border-slate-200 dark:border-slate-800 p-4 hidden lg:block overflow-y-auto">
        <h2 className="text-sm font-semibold mb-2">工具调用时间线</h2>
        <ToolCallTimeline />
        <h2 className="text-sm font-semibold mt-6 mb-2">附件</h2>
        <AttachmentUploader />
      </aside>
    </div>
  );
}