// Status describes the local Codex bridge, not guaranteed cloud/model success.
export function chatConnection(health, reachable = true) {
  const online =
    reachable && health?.chat_ready === true && !health?.chat_error;
  return {
    online,
    label: online ? "online" : "offline",
    description: online
      ? "Codex 本地连接可用"
      : !reachable
        ? "本机服务连接已中断"
        : health?.chat_error || "Codex 连接不可用",
  };
}
