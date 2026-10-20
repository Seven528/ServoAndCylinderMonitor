"""在 VS Code 打开本文件，点击 Run Python File 即可启动并打开网页。"""

from __future__ import annotations

import errno
import http.client
import json
import sys
import webbrowser
from pathlib import Path

# 可直接修改；无需配置命令行参数或切换工作目录。
WEB_PORT = 8890
OPEN_BROWSER = True


def _is_agent_running(port: int) -> bool:
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request('GET', '/api/health')
        response = connection.getresponse()
        payload = json.loads(response.read(4096))
        return (response.status == 200 and isinstance(payload, dict) and payload.get('agent') == 'local-statistical-v1'
                and payload.get('local_only') is True)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def main():
    project_root = Path(__file__).resolve().parent
    source_root = project_root / 'Web_Framework' / 'source'
    sys.path.insert(0, str(source_root))
    try:
        from integrations.servo_cylinder_agent.server import main as serve
    except ModuleNotFoundError as error:
        print(f'当前 Python 环境缺少依赖：{error.name}。')
        print('请在 VS Code 选择已安装 pandas、numpy、openpyxl 的 Python 解释器。')
        raise SystemExit(1) from None

    arguments = ['--port', str(WEB_PORT)]
    if OPEN_BROWSER:
        arguments.append('--open')
    try:
        serve(arguments)
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE, 10048):
            raise
        url = f'http://127.0.0.1:{WEB_PORT}/'
        if not _is_agent_running(WEB_PORT):
            print(f'端口 {WEB_PORT} 被其他程序占用，请修改本文件的 WEB_PORT 后再运行。')
            raise SystemExit(1) from None
        print(f'分析工作台已在运行，打开现有服务：{url}', flush=True)
        print('如需重启服务，请先在原启动终端按 Ctrl+C。', flush=True)
        if OPEN_BROWSER:
            webbrowser.open(url)


if __name__ == '__main__':
    main()
