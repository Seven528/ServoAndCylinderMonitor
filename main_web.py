"""在 VS Code 打开本文件，点击 Run Python File 即可启动并打开网页。"""

from __future__ import annotations

import errno  # cspell:ignore EADDRINUSE
import http.client
import json
import webbrowser

from src.web_logging import get_logger

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
    try:
        from Web_Framework.source.integrations.servo_cylinder_agent.server import main as serve
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
        get_logger().write_log('INFO', 'web.launcher', f'existing_service | port={WEB_PORT}')
        print(f'分析工作台已在运行，打开现有服务：{url}', flush=True)
        print('如需重启服务，请先在原启动终端按 Ctrl+C。', flush=True)
        if OPEN_BROWSER:
            webbrowser.open(url)


if __name__ == '__main__':
    with get_logger().run(__file__):
        main()
