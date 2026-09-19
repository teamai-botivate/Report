"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-sm font-semibold">Something went wrong</p>
      <p className="max-w-md text-xs text-muted-foreground">{error.message}</p>
      <Button size="sm" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
