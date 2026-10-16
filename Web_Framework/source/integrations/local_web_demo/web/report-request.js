// Report export is an explicit user-turn action, not a property of every reply.
export function requestsReportExport(text) {
  const plain = String(text || "").replace(
    /"[^"\n]*"|“[^”]*”|「[^」]*」|‘[^’]*’/gu,
    "",
  );
  if (
    /(?:不要|不用|无需|不需要|不必|不(?:生成|制作|导出|下载|输出)|别|禁止|停止)[^。！？\n]{0,24}(?:报告|导出|下载|附件)|\b(?:do not|don't|no need to)\b[^.!?\n]{0,40}\b(?:report|export|download)\b/iu.test(
      plain,
    )
  )
    return false;
  if (
    /(?:为什么|为何|怎么会|谁让)[^。！？\n]{0,24}(?:报告|生成|导出|下载)/u.test(
      plain,
    )
  )
    return false;
  return /(?:生成|导出|下载|制作|输出|整理|给我|提供|发我|做一份)[^。！？\n]{0,30}报告|报告[^。！？\n]{0,16}(?:导出|下载|发我|给我)|\b(?:generate|create|export|download|write)\b[^.!?\n]{0,40}\breport\b/iu.test(
    plain,
  );
}

export function replyReportRequested(message, snapshot) {
  const index = (snapshot.messages || []).findIndex(
    (item) => item.id === message.id,
  );
  if (index < 0) return false;
  const user = snapshot.messages
    .slice(0, index)
    .findLast((item) => item.role === "user");
  return requestsReportExport(user?.text);
}
