"use client";

import * as React from "react";
import { TopBar } from "./TopBar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
