// Adapted from the supplied template: escape first, then render a small Markdown subset.
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const inline = (s) =>
  esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
export function markdown(text) {
  const lines = text.split("\n");
  let html = "",
    paragraph = [],
    items = [];
  const flush = () => {
    if (paragraph.length) {
      html += "<p>" + paragraph.map(inline).join("<br>") + "</p>";
      paragraph = [];
    }
    if (items.length) {
      html +=
        "<ul>" +
        items.map((s) => "<li>" + inline(s) + "</li>").join("") +
        "</ul>";
      items = [];
    }
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (
      line.includes("|") &&
      /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")
    ) {
      flush();
      const cells = (s) =>
        s
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((x) => inline(x.trim()));
      html +=
        '<div class="chat-table"><table><thead><tr>' +
        cells(line)
          .map((c) => "<th>" + c + "</th>")
          .join("") +
        "</tr></thead><tbody>";
      i++;
      while (i + 1 < lines.length && lines[i + 1].includes("|")) {
        html +=
          "<tr>" +
          cells(lines[++i])
            .map((c) => "<td>" + c + "</td>")
            .join("") +
          "</tr>";
      }
      html += "</tbody></table></div>";
    } else if (/^[-*] /.test(line)) {
      if (paragraph.length) flush();
      items.push(line.slice(2));
    } else if (!line.trim()) {
      flush();
    } else {
      if (items.length) flush();
      paragraph.push(line.replace(/^#{1,4}\s/, ""));
    }
  }
  flush();
  return html;
}
