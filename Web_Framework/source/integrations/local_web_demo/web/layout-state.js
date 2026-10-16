// Presentation preferences only. No source, task, result or image ownership.
export function createLayoutState(initial = {}, initialWidth = 1280) {
  let files = initial.files === true,
    chat =
      typeof initial.chat === "boolean" ? initial.chat : initialWidth >= 1280;
  let section = initial.section === "history" ? "history" : "files";
  let last = initial.last === "chat" ? "chat" : "files";
  let focused = false;
  return {
    toggle(name, requestedSection = section) {
      if (!["files", "chat"].includes(name)) return;
      focused = false;
      if (name === "files") {
        files = section !== requestedSection || !files;
        section = requestedSection === "history" ? "history" : "files";
      } else chat = !chat;
      last = name;
    },
    close(name) {
      if (name === "files") files = false;
      if (name === "chat") chat = false;
    },
    focus(value = !focused) {
      focused = value;
    },
    project(width) {
      let f = "closed",
        c = "closed";
      if (!focused) {
        if (width >= 1280) {
          c = chat ? "docked" : "closed";
          f = files ? (chat && width < 1600 ? "drawer" : "docked") : "closed";
        } else if (files || chat) {
          const active = files && chat ? last : files ? "files" : "chat";
          if (active === "files") f = "drawer";
          else c = "drawer";
        }
      }
      return {
        files: f,
        chat: c,
        section,
        focused,
        overlay: f === "drawer" ? "files" : c === "drawer" ? "chat" : null,
      };
    },
    serialize: () => ({ files, chat, section, last }),
  };
}
