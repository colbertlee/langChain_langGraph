import { AssistantRuntimeProvider } from '@assistant-ui/react';
import { SessionList } from '@/components/chat/SessionList';
import { Thread } from '@/components/assistant-ui/thread';
import { useAgentThreadListRuntime } from '@/hooks/useAgentThreadListRuntime';

export function Chat() {
  const runtime = useAgentThreadListRuntime();
  return (
    <div className="h-full flex">
      <SessionList />
      <div className="flex-1 flex flex-col min-w-0">
        <AssistantRuntimeProvider runtime={runtime}>
          <Thread />
        </AssistantRuntimeProvider>
      </div>
    </div>
  );
}
