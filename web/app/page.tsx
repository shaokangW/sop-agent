"use client";
import { useMeowStore } from "@/lib/store";
import { useMeowWorkWS } from "@/lib/ws";
import TaskInput from "@/components/TaskInput";
import StatusBar from "@/components/StatusBar";
import PlannerPanel from "@/components/PlannerPanel";
import ExecutorPanel from "@/components/ExecutorPanel";
import ReviewerPanel from "@/components/ReviewerPanel";
import ValidatorPanel from "@/components/ValidatorPanel";

export default function Page() {
  const runId = useMeowStore((s) => s.runId);
  useMeowWorkWS(runId); // connect when a run starts

  return (
    <div className="h-screen flex flex-col bg-bg text-text">
      <TaskInput />
      <StatusBar />
      <div className="flex-1 grid grid-cols-[280px_1fr_300px] grid-rows-[1fr_1fr] gap-px bg-border overflow-hidden">
        <div className="row-span-2 overflow-hidden"><PlannerPanel /></div>
        <div className="overflow-hidden"><ExecutorPanel /></div>
        <div className="overflow-hidden"><ReviewerPanel /></div>
        <div className="row-span-2 overflow-hidden"><ValidatorPanel /></div>
      </div>
    </div>
  );
}
