export function createConnectionRecovery({ now = Date.now } = {}) {
  let failures = 0,
    next = 0;
  return {
    get recovering() {
      return failures > 0;
    },
    get ready() {
      return now() >= next;
    },
    failure() {
      const seconds = [1, 2, 4, 8, 10][Math.min(failures, 4)];
      failures++;
      next = now() + seconds * 1000;
      return seconds;
    },
    success() {
      failures = 0;
      next = 0;
    },
    retryNow() {
      next = 0;
    },
  };
}
