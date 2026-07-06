"use client";
import { useMeowStore } from "@/lib/store";
import { useMeowWorkWS } from "@/lib/ws";
import TaskInput from "@/components/TaskInput";
import AgentSidebar from "@/components/AgentSidebar";
import ChatStream from "@/components/ChatStream";

export default function Page() {
  const groupId = useMeowStore((s) => s.groupId);
  useMeowWorkWS(groupId);

  return (
    <div className="h-screen flex flex-col bg-bg">
      <TaskInput />
      <div className="flex-1 flex overflow-hidden">
        <AgentSidebar />
        <ChatStream />
      </div>
    </div>
  );
}
