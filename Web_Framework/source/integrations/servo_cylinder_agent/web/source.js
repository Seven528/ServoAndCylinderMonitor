// Source configuration and connection UI. Passwords are never persisted in browser storage.
export function setupSources({ api, pollJob, notice }) {
  const $ = (id) => document.getElementById(id);
  let connectionId = '', busy = false, localFileId = '';
  function status(message, kind = '') { $('ch-status').textContent = message; $('ch-status').className = `source-status ${kind}`; }
  function refresh() {
    const remote = $('source-kind').value === 'clickhouse';
    $('csv-source').hidden = remote; $('clickhouse-source').hidden = !remote;
    $('analyze').disabled = busy || (remote ? !connectionId : !localFileId);
    $('source-controls').disabled = busy;
  }
  function setBusy(value) { busy = value; refresh(); }
  function selectedFile(result) {
    localFileId = result.file_id;
    $('local-selection').textContent = `已选择：${result.name}（${(result.bytes / 1024 / 1024).toFixed(1)} MiB）`;
    $('local-selection').className = 'source-status success';
    $('local-sheet').replaceChildren(...result.sheets.map((name) => new Option(name, name)));
    $('local-sheets').hidden = result.sheets.length === 0;
  }
  async function selectFile(action) {
    localFileId = ''; $('local-sheets').hidden = true;
    $('local-selection').textContent = '正在检查所选文件…';
    setBusy(true);
    try { selectedFile(await action()); }
    catch (error) { $('local-selection').textContent = error.message; $('local-selection').className = 'source-status error'; }
    finally { setBusy(false); }
  }
  async function selectProject() {
    if (!$('dataset').value) return;
    await selectFile(() => api('/api/local/project', {method:'POST',body:JSON.stringify({dataset:$('dataset').value})}));
  }
  $('use-project-file').addEventListener('click', selectProject);
  $('dataset').addEventListener('change', selectProject);
  $('pick-local-file').addEventListener('click', () => $('local-file').click());
  $('local-file').addEventListener('change', async () => {
    const file = $('local-file').files[0];
    if (!file) return;
    await selectFile(async () => {
      if (file.size > 128 * 1024 * 1024) throw new Error('浏览器选择上限 128 MiB，更大 CSV 请使用绝对路径。');
      return api(`/api/local/upload?filename=${encodeURIComponent(file.name)}`, {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    });
    $('local-file').value = '';
  });
  $('use-local-path').addEventListener('click', () => selectFile(() => api('/api/local/register', {method:'POST',body:JSON.stringify({path:$('local-path').value})})));
  function invalidate() {
    connectionId = ''; $('ch-query').hidden = true;
    status('连接配置已更改，请重新检查连接。'); refresh();
  }
  for (const id of ['ch-endpoint','ch-database','ch-table','ch-username','ch-password']) $(id).addEventListener('input', invalidate);
  $('source-kind').addEventListener('change', refresh);
  function fillColumns(id, columns, optional = false) {
    const select = $(id); select.replaceChildren();
    if (optional) { const option = new Option('不筛选', ''); select.append(option); }
    for (const item of columns) select.append(new Option(`${item.name} · ${item.type}`, item.name));
  }
  const localTime = (value) => value.toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ', 'T').slice(0,16);
  $('ch-start').value = localTime(new Date(Date.now()-3600*1000));
  $('ch-end').value = localTime(new Date());
  $('ch-connect').addEventListener('click', async () => {
    const config = Object.fromEntries(['endpoint','database','table','username','password'].map((key) => [key, $(`ch-${key}`).value]));
    if (!config.endpoint || !config.database || !config.table || !config.username) { status('请填写 API 地址、数据库、表名和用户名。', 'error'); return; }
    connectionId = ''; setBusy(true); status('正在检查连接并读取字段…');
    try {
      const job = await api('/api/clickhouse/connect', {method:'POST', body:JSON.stringify(config)});
      const result = await pollJob(job.job_id, (message) => status(message));
      const dates = result.columns.filter((c) => c.type.includes('DateTime'));
      if (!dates.length) throw new Error('目标表没有 DateTime/DateTime64 时间字段，暂不能执行时间范围分析。');
      connectionId = result.connection_id;
      fillColumns('ch-time-column', dates); fillColumns('ch-station-column', result.columns, true);
      $('ch-time-column').value = dates.find((c) => c.name.toUpperCase() === 'MSG_TIMESTAMP')?.name || dates[0].name;
      $('ch-station-column').value = result.columns.find((c) => c.name.toUpperCase() === 'STATIONNAME')?.name || '';
      $('ch-password').value = ''; // The opaque connection ID replaces the password after checking.
      $('ch-query').hidden = false;
      status(`连接成功，已读取 ${result.columns.length} 个字段。请设置时间范围。`, 'success');
      notice('ClickHouse 连接已就绪。选择时间与站点范围后运行分析。', 'success');
    } catch (error) { connectionId = ''; status(error.message, 'error'); }
    finally { setBusy(false); }
  });
  refresh();
  return {
    setBusy,
    selectProject,
    setCsvAvailable(value) { $('use-project-file').disabled = !value; refresh(); },
    request() {
      if ($('source-kind').value === 'csv') {
        if (!localFileId) throw new Error('请先选择有效的本地文件。');
        const body = {local_file_id:localFileId};
        if (!$('local-sheets').hidden) body.sheet = $('local-sheet').value;
        return {path:'/api/analyze',body};
      }
      if (!connectionId) throw new Error('请先检查 ClickHouse 连接。');
      const start = $('ch-start').value, end = $('ch-end').value;
      if (!start || !end) throw new Error('请选择开始和结束时间。');
      return {path:'/api/clickhouse/analyze', body:{connection_id:connectionId, options:{
        time_column:$('ch-time-column').value, start, end,
        station_column:$('ch-station-column').value, station:$('ch-station').value,
        max_rows:Number($('ch-max-rows').value),
      }}};
    },
  };
}
