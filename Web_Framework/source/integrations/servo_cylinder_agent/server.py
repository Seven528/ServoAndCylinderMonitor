"""Loopback web service for local servo and pneumatic cylinder analytics."""

from __future__ import annotations

import json
import mimetypes
import secrets
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

from .analysis import PROJECT_ROOT, analyze_dataset, analyze_frame, save_result

from .clickhouse_source import Connection, build_read, read_frame
from .local_source import inspect_file, validate_file
from .agent_models import AnswerModels, LOCAL_MODEL
from src.web_logging import get_logger, log_failure

DATA_ROOT = PROJECT_ROOT / "data" / "input"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "output" / "web_agent_runs"
WEB_ROOT = Path(__file__).resolve().parent / "web"
MAX_DATASET_BYTES = 1024 * 1024 * 1024
MAX_UPLOAD_BYTES = 128 * 1024 * 1024


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.server_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="servo-analysis")
        self.jobs: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.connections = {}
        self.answer_models = AnswerModels()
        self.local_files = {}
        self.upload_directory = tempfile.TemporaryDirectory(prefix='servo-web-')
        self.upload_bytes = 0
        get_logger().write_log('INFO', 'web.server', f'SERVER_START | port={self.server_address[1]}')

    def datasets(self):
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        items = []
        for path in DATA_ROOT.rglob('*'):
            if path.suffix.lower() not in ('.csv', '.xlsx') or path.name == 'param_name_and_type.xlsx':
                continue
            if not path.is_file() or "web_uploads" in path.parts:
                continue
            try:
                relative = path.relative_to(DATA_ROOT).as_posix()
                size = path.stat().st_size
            except OSError:
                continue
            if size <= MAX_DATASET_BYTES:
                items.append({"id": relative, "name": path.name, "bytes": size})
        return sorted(items, key=lambda item: item["name"], reverse=True)

    def resolve_dataset(self, dataset_id: str) -> Path:
        available = {item["id"] for item in self.datasets()}
        if dataset_id not in available:
            raise ValueError("数据集不在 data/input 允许目录中。")
        path = (DATA_ROOT / dataset_id).resolve()
        if not path.is_relative_to(DATA_ROOT.resolve()) or path.suffix.lower() not in (".csv", ".xlsx"):
            raise ValueError("数据集路径无效。")
        if path.stat().st_size > MAX_DATASET_BYTES:
            raise ValueError("当前版本单个 CSV 上限为 1 GiB。")
        return path

    def server_close(self):
        self.answer_models.close()
        super().server_close()
        if hasattr(self, 'upload_directory'):
            self.upload_directory.cleanup()
            get_logger().write_log('INFO', 'web.server', f'SERVER_STOP | port={self.server_address[1]}')

    def register_local(self, path):
        if not isinstance(path, str) or not path.strip():
            raise ValueError('请选择文件或输入绝对路径。')
        selected = validate_file(path.strip().strip('"'))
        details = inspect_file(selected)
        with self.lock:
            if len(self.local_files) >= 40:
                raise ValueError('本次会话最多选择 40 个文件，请重启服务后重新选择。')
            fid = secrets.token_urlsafe(24)
            self.local_files[fid] = selected
        get_logger().write_log('INFO', 'web.files', f"FILE_SELECTED | name={details['name']!r} | bytes={details['bytes']}")
        return {'file_id': fid, **details}

    def _new_job(self, label, stage):
        with self.lock:
            if any(job['status'] in ('queued', 'running') for job in self.jobs.values()):
                raise ValueError('已有任务正在执行，请等待完成。')
            if len(self.jobs) >= 64:
                self.jobs.pop(next(iter(self.jobs)))
            jid = 'j_' + uuid.uuid4().hex
            self.jobs[jid] = {'id': jid, 'status': 'queued', 'dataset': label, 'stage': stage}
            get_logger().write_log('INFO', 'web.jobs', f'JOB_QUEUED | job={jid} | source={label!r}')
            return jid

    def start_connection(self, body):
        connection = Connection.parse(body)
        jid = self._new_job('ClickHouse', '正在检查连接和目标表字段')
        self.executor.submit(self._connect, jid, connection)
        return {'job_id': jid, 'status': 'queued'}

    def _connect(self, jid, connection):
        try:
            with self.lock:
                self.jobs[jid]['status'] = 'running'
            get_logger().write_log('INFO', 'web.clickhouse', f'CONNECT_START | table={connection.database}.{connection.table}')
            columns = connection.check()
            get_logger().write_log('INFO', 'web.clickhouse', f'CONNECT_SUCCESS | fields={len(columns)}')
            cid = secrets.token_urlsafe(24)
            with self.lock:
                self.connections = {key: value for key, value in self.connections.items() if value['expires'] > time.monotonic()}
                while len(self.connections) >= 8:
                    self.connections.pop(next(iter(self.connections)))
                self.connections[cid] = {'connection': connection, 'columns': columns, 'expires': time.monotonic()+3600}
                self.jobs[jid].update(status='succeeded', result={'connection_id': cid, 'columns': columns})
        except Exception as error:
            log_failure('web.clickhouse', error, f'CONNECT_FAILED | job={jid}', secrets=(connection.username, connection.password))
            with self.lock:
                self.jobs[jid].update(status='failed', error=str(error)[:500])

    def start_clickhouse_analysis(self, body):
        with self.lock:
            selected = self.connections.get(str(body.get('connection_id', '')))
        if not selected or selected['expires'] <= time.monotonic():
            raise ValueError('ClickHouse 连接已失效，请重新检查连接。')
        options = body.get('options')
        build_read(selected['connection'], selected['columns'], options)
        jid = self._new_job('ClickHouse', '正在按时间范围读取 ClickHouse')
        self.executor.submit(self._analyze_clickhouse, jid, selected, options)
        return {'job_id': jid, 'status': 'queued'}

    def _analyze_clickhouse(self, jid, selected, options):
        try:
            with self.lock:
                self.jobs[jid].update(status='running')
            frame, source = read_frame(selected['connection'], selected['columns'], options)
            with self.lock:
                self.jobs[jid]['stage'] = '已读取数据，正在执行分析'
            dictionary = DATA_ROOT / 'param_name_and_type.xlsx'
            result = analyze_frame(frame, f"ClickHouse · {source['database']}.{source['table']}",
                                   dictionary if dictionary.exists() else None, source=source)
            self._publish(jid, result)
        except Exception as error:
            connection = selected['connection']
            log_failure('web.clickhouse', error, f'ANALYSIS_FAILED | job={jid}', secrets=(connection.username, connection.password))
            with self.lock:
                self.jobs[jid].update(status='failed', stage='分析失败', error=str(error)[:500])

    def _publish(self, jid, result):
        save_result(result, OUTPUT_ROOT)
        get_logger().write_log('INFO', 'web.analysis', f"ANALYSIS_COMPLETE | job={jid} | run={result['run_id']} | rows={result['descriptive']['top_level']['rows']}")
        with self.lock:
            self.results[result['run_id']] = result
            self.jobs[jid].update(status='succeeded', stage='分析完成', result=result)
            while len(self.results) > 5:
                self.results.pop(next(iter(self.results)))

    def start_analysis(self, dataset_id=None, local_file_id=None, sheet=None):
        if local_file_id is not None:
            with self.lock:
                path = self.local_files.get(local_file_id)
            if path is None:
                raise ValueError('本地文件选择已失效，请重新选择。')
            path = validate_file(path)
        else:
            path = self.resolve_dataset(dataset_id)
        if sheet is not None and not isinstance(sheet, str):
            raise ValueError('工作表名称无效。')
        jid = self._new_job(path.name, '等待读取本地数据')
        self.executor.submit(self._analyze, jid, path, sheet)
        return {'job_id': jid, 'status': 'queued'}

    def _analyze(self, jid, path, sheet=None):
        with self.lock:
            self.jobs[jid].update(status='running', stage='读取并校验数据')
        try:
            get_logger().write_log('INFO', 'web.files', f'READ_START | job={jid} | name={path.name!r} | sheet={sheet!r}')
            dictionary = DATA_ROOT / 'param_name_and_type.xlsx'
            result = analyze_dataset(path, dictionary if dictionary.exists() else None, sheet)
            self._publish(jid, result)
        except Exception as error:
            log_failure('web.analysis', error, f'ANALYSIS_FAILED | job={jid}')
            with self.lock:
                self.jobs[jid].update(status='failed', stage='分析失败', error=str(error)[:500])

    def start_model_connection(self):
        jid = self._new_job('Codex', '正在读取本机 Codex 模型列表')
        self.executor.submit(self._connect_models, jid)
        return {'job_id':jid}

    def _connect_models(self, jid):
        try:
            with self.lock:
                self.jobs[jid]['status'] = 'running'
            result = self.answer_models.connect()
            with self.lock:
                self.jobs[jid].update(status='succeeded', result=result)
        except Exception as error:
            log_failure('web.models', error, f'CONNECT_FAILED | job={jid}')
            with self.lock:
                self.jobs[jid].update(status='failed',error=str(error)[:500])

    def start_model_answer(self, run_id, question, settings, consent):
        self.answer_models.validate(settings)
        if consent is not True:
            raise ValueError('请先确认将问题和分析摘要发送至所选模型。')
        with self.lock:
            result = self.results.get(run_id)
        if result is None:
            raise ValueError('分析结果已过期，请重新分析。')
        jid = self._new_job('模型问答','所选模型正在回答')
        self.executor.submit(self._answer_model,jid,result,question,settings,consent)
        return {'job_id':jid}

    def _answer_model(self,jid,result,question,settings,consent):
        try:
            with self.lock:
                self.jobs[jid]['status'] = 'running'
            answer = self.answer_models.answer(result,question,settings,consent)
            get_logger().write_log('INFO','web.models',f"ANSWER_COMPLETE | job={jid} | model={settings['model']}")
            with self.lock:
                self.jobs[jid].update(status='succeeded',result=answer)
        except Exception as error:
            log_failure('web.models',error,f'ANSWER_FAILED | job={jid}')
            with self.lock:
                self.jobs[jid].update(status='failed',error=str(error)[:500])

    def ask(self, run_id: str, question: str):
        with self.lock:
            result = self.results.get(run_id)
        if result is None:
            raise ValueError("分析结果已过期，请重新运行分析。")
        text = question.strip().lower()
        if any(word in text for word in ("剩余寿命", "寿命", "rul", "预测", "还能用")):
            p = result["predictive"]
            return {"topic": "predictive", "answer": p["message"], "evidence": p["reasons"], "models": p["candidate_models"]}
        if any(word in text for word in ("生命周期", "健康", "状态", "劣化")):
            l = result["lifecycle"]
            return {"topic": "lifecycle", "answer": l["method"], "evidence": l["assets"], "notes": l["notes"]}
        if any(word in text for word in ("异常", "诊断", "报警", "故障")):
            d = result["diagnostic"]
            return {"topic": "diagnostic", "answer": "以下是本次数据窗的异常筛查统计，属于待复核信号。", "evidence": d["flag_counts"], "notes": d["notes"]}
        return {"topic": "descriptive", "answer": "以下是本次导出数据的范围和关键描述统计。", "evidence": result["descriptive"]["top_level"], "assets": result["descriptive"]["assets"]}


class Handler(BaseHTTPRequestHandler):
    server: AgentServer

    def log_message(self, *_args):
        pass

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _origin_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Origin") in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _auth_ok(self):
        return secrets.compare_digest(self.headers.get("X-Agent-Token", ""), self.server.token)

    def _send(self, status: int, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 16_384:
            raise ValueError("请求内容大小无效。")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("请求必须是 JSON。")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是对象。")
        return value

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "仅支持本机访问。"})
        url = urlsplit(self.path)
        if url.path == "/api/health":
            return self._send(200, {"token": self.server.token, "server_id": self.server.server_id,
                                    "agent": "local-statistical-v1", "local_only": True})
        if url.path == "/":
            return self._static("index.html")
        if url.path.startswith("/web/"):
            return self._static(unquote(url.path.removeprefix("/web/")))
        if not self._auth_ok():
            return self._send(403, {"error": "网页会话已失效，请刷新。"})
        if url.path == '/api/models':
            return self._send(200,self.server.answer_models.catalog())
        if url.path == "/api/datasets":
            return self._send(200, {"datasets": self.server.datasets()})
        if url.path.startswith("/api/jobs/"):
            jid = url.path.rsplit("/", 1)[-1]
            with self.server.lock:
                job = self.server.jobs.get(jid)
            return self._send(200, job or {"error": "任务不存在。"})
        return self._send(404, {"error": "页面不存在。"})

    def _static(self, relative):
        path = (WEB_ROOT / relative).resolve()
        if not path.is_relative_to(WEB_ROOT.resolve()) or not path.is_file():
            return self._send(404, {"error": "页面不存在。"})
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in {"application/javascript", "image/svg+xml"}:
            mime += "; charset=utf-8"
        return self._send(200, path.read_bytes(), mime)

    def _upload(self):
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= MAX_UPLOAD_BYTES:
            raise ValueError('浏览器选择文件上限为 128 MiB；更大 CSV 请使用绝对路径。')
        name = parse_qs(urlsplit(self.path).query).get('filename', [''])[0]
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        if not name or Path(name).suffix.lower() not in ('.csv', '.xlsx') or len(name) > 240:
            raise ValueError('请选择 CSV 或 XLSX 文件。')
        with self.server.lock:
            if self.server.upload_bytes + size > 512 * 1024 * 1024:
                raise ValueError('本次会话文件累计超过 512 MiB，请重启后重新选择，或使用绝对路径。')
            self.server.upload_bytes += size
        folder = Path(self.server.upload_directory.name) / uuid.uuid4().hex
        folder.mkdir()
        path = folder / name
        previous_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(30)
            remaining = size
            with path.open('wb') as stream:
                while remaining:
                    chunk = self.rfile.read(min(1024*1024, remaining))
                    if not chunk:
                        raise ValueError('文件传输未完成，请重新选择。')
                    stream.write(chunk)
                    remaining -= len(chunk)
            result = self.server.register_local(str(path))
            return self._send(200, result)
        except Exception:
            with self.server.lock:
                self.server.upload_bytes -= size
            path.unlink(missing_ok=True)
            raise
        finally:
            self.connection.settimeout(previous_timeout)

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._send(403, {"error": "请从本机 Agent 页面操作。"})
        if not self._auth_ok():
            return self._send(403, {"error": "网页会话已失效，请刷新。"})
        try:
            url = urlsplit(self.path)
            if url.path == '/api/local/upload':
                return self._upload()
            body = self._body()
            if url.path == '/api/local/project':
                return self._send(200, self.server.register_local(str(self.server.resolve_dataset(body.get('dataset')))))
            if url.path == '/api/local/register':
                return self._send(200, self.server.register_local(body.get('path')))
            if url.path == '/api/models/connect':
                return self._send(202,self.server.start_model_connection())
            if url.path == '/api/clickhouse/connect':
                return self._send(202, self.server.start_connection(body))
            if url.path == '/api/clickhouse/analyze':
                return self._send(202, self.server.start_clickhouse_analysis(body))
            if url.path == "/api/analyze":
                keys = set(body)
                if keys not in ({'dataset'}, {'dataset', 'sheet'}, {'local_file_id'}, {'local_file_id', 'sheet'}):
                    raise ValueError('请选择一个有效的本地数据文件。')
                source = body.get('local_file_id', body.get('dataset'))
                if not isinstance(source, str):
                    raise ValueError('本地文件标识无效。')
                return self._send(202, self.server.start_analysis(body.get('dataset'), body.get('local_file_id'), body.get('sheet')))
            if url.path == "/api/ask":
                run_id, question = body.get("run_id"), body.get("question")
                if not isinstance(run_id, str) or not isinstance(question, str) or not question.strip() or len(question) > 1000:
                    raise ValueError("请提供分析结果 ID 和不超过 1000 字的问题。")
                settings = body.get('settings', {'model':LOCAL_MODEL['id']})
                settings = self.server.answer_models.validate(settings)
                if settings['model'] != LOCAL_MODEL['id']:
                    return self._send(202,self.server.start_model_answer(run_id,question,settings,body.get('consent')))
                answer = self.server.ask(run_id, question)
                answer['settings'] = settings
                return self._send(200, answer)
        except Exception as error:  # noqa: BLE001 - bounded local API error
            log_failure('web.api', error, f'REQUEST_FAILED | route={urlsplit(self.path).path}')
            return self._send(400, {"error": str(error)[:500]})
        return self._send(404, {"error": "接口不存在。"})

    def do_OPTIONS(self):
        return self._send(405, {"error": "不支持该请求。"})


def main(argv=None):
    import argparse
    import signal

    parser = argparse.ArgumentParser(description="Local servo/cylinder analytics workbench")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    server = AgentServer(args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"伺服与气缸分析 Agent：{url}\n本地数据目录：{DATA_ROOT}\n按 Ctrl+C 退出。", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.answer_models.close()
        server.executor.shutdown(wait=True, cancel_futures=True)
        server.server_close()


if __name__ == "__main__":
    with get_logger().run(__file__):
        main()
