// Names come from typed uploaded-file IDs and proven result contexts, never filenames guessed from output paths.
export function historySubjects(job, files) {
  const byId = new Map(files.map((file) => [file.id, file.name]));
  const names = [];
  const add = (name) => {
    if (name && !names.includes(name)) names.push(name);
  };
  const visit = (value) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (
        [
          "pcb_file_id",
          "holder_file_id",
          "baseline_file_id",
          "target_file_id",
        ].includes(key)
      )
        add(byId.get(child));
      else if (key === "file_ids" && Array.isArray(child))
        child.forEach((id) => add(byId.get(id)));
      else visit(child);
    }
  };
  visit(job.arguments);
  for (const view of job.presentations || []) {
    add(view.context?.file_name);
    add(view.context?.holder_name);
  }
  return names;
}
