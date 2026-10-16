import test from "node:test";
import assert from "node:assert/strict";
import { historySubjects } from "../web/history-subjects.js";
import { analysisDocument } from "../web/message-downloads.js";
import { pcmWav } from "../web/local-recognition.js";
import {
  requestsReportExport,
  replyReportRequested,
} from "../web/report-request.js";

test("history names identify all requested files before results exist", () => {
  const files = [
    { id: "a", name: "a.uni" },
    { id: "b", name: "b.uni" },
    { id: "h", name: "holder.uni" },
  ];
  assert.deepEqual(
    historySubjects(
      {
        arguments: {
          holder_file_id: "h",
          analysis: { pcbs: [{ pcb_file_id: "a" }, { pcb_file_id: "b" }] },
        },
        presentations: [],
      },
      files,
    ),
    ["holder.uni", "a.uni", "b.uni"],
  );
});
test("analysis HTML escapes source text and Markdown preserves it", async () => {
  const message = {
    text: "<script>alert(1)</script>\n\n**结果**",
    status: "completed",
  };
  const html = await analysisDocument(message).text();
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(
    (await analysisDocument(message, "md").text()).includes(message.text),
  );
});
test("local WAV encoding is mono PCM16 and duration bounded", async () => {
  const wav = pcmWav([new Float32Array([-1, 0, 1])]);
  const bytes = await wav.arrayBuffer();
  const v = new DataView(bytes);
  assert.equal(v.getUint16(22, true), 1);
  assert.equal(v.getUint32(24, true), 16000);
  assert.equal(v.getUint16(34, true), 16);
  assert.equal(v.getInt16(44, true), -32768);
  assert.equal(v.getInt16(48, true), 32767);
  assert.equal(
    pcmWav([new Float32Array(16000 * 61)]).size,
    44 + 16000 * 60 * 2,
  );
});

test("report exports are offered only for an explicit request", () => {
  for (const text of [
    "你好，可以听见我吗",
    "请告诉我压棒有没有干涉",
    "请读取报告里的NDH1",
    "不要生成报告，只回答数字",
    "请执行分析，简要汇总，不生成下载报告。",
    "只分析，不导出报告",
    "为什么自动生成报告",
    "解释一下‘生成报告’是什么意思",
  ])
    assert.equal(requestsReportExport(text), false, text);
  for (const text of [
    "请生成本次分析的报告",
    "把结果整理成报告",
    "给我一份报告",
    "请导出报告",
    "Please generate a report",
  ])
    assert.equal(requestsReportExport(text), true, text);
});
test("report permission belongs to one reply, not subsequent greetings", () => {
  const first = { id: "a1", role: "assistant", text: "报告" },
    second = { id: "a2", role: "assistant", text: "你好" };
  const snapshot = {
    messages: [
      { id: "u1", role: "user", text: "请生成报告" },
      first,
      { id: "u2", role: "user", text: "你好" },
      second,
    ],
  };
  assert.equal(replyReportRequested(first, snapshot), true);
  assert.equal(replyReportRequested(second, snapshot), false);
});
