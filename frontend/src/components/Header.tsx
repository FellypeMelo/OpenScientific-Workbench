"use client";

import { useAuth } from "@/lib/auth";

/**
 * Small status header shown at the top of the chat panel: app title, BYOK
 * badge, and the current dev-mode auth state (loading / error / short user id)
 * -- a real (if minimal) reflection of `AuthProvider`'s state, replacing the
 * previous build's complete absence of any auth UI.
 */
export function Header() {
  const { userId, isLoading, error } = useAuth();

  let statusLabel: string;
  if (isLoading) {
    statusLabel = "auth...";
  } else if (error) {
    statusLabel = "auth error";
  } else if (userId) {
    statusLabel = `user ${userId.slice(0, 8)}`;
  } else {
    statusLabel = "unauthenticated";
  }

  return (
    <div className="flex items-center justify-between pb-2 border-b border-[#1a1a24]">
      <h1 className="text-lg font-bold tracking-tight text-white">OSW Workbench</h1>
      <div className="flex items-center gap-2">
        <span className="text-xs bg-[#242435] text-[#a0a0b8] px-2 py-1 rounded-md font-mono">
          BYOK
        </span>
        <span
          data-testid="auth-status"
          className={`text-[10px] px-2 py-1 rounded-md font-mono ${
            error ? "bg-[#2a1010] text-[#ff8686]" : "bg-[#0f2a24] text-[#86ffcf]"
          }`}
        >
          {statusLabel}
        </span>
      </div>
    </div>
  );
}
