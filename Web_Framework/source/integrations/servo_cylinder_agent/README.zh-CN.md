# 伺服与气缸分析 Agent

这是 `Web_Framework` 中独立运行的本地分析集成。它复用该框架“小型 Python HTTP 服务 + 原生 HTML/CSS/ES Modules”模式，不依赖 PCB 原生引擎、MCP SDK 或外部模型。

## 启动

在 VS Code 打开项目根目录的 `main_web.py`，选择已安装 `pandas`、`numpy`、`openpyxl` 的 Python 解释器，点击右上角 **Run Python File**。脚本会启动服务并自动打开浏览器；不需要命令行参数，不依赖终端当前目录。

保持该终端运行；按 **Ctrl+C** 停止。重复运行时，如同一端口已有本项目服务，会打开现有服务；如果端口被其他程序占用，会提示修改 `main_web.py` 中的 `WEB_PORT`。更新后需要重启时，应先在原终端停止服务。

也可从 `Web_Framework/source` 执行：

```sh
python -m integrations.servo_cylinder_agent.server --port 8890
```

访问 `http://127.0.0.1:8890`。服务只绑定本机回环地址。CSV 文件放在项目的 `data/input` 目录后，可在网页数据源下拉框选择；单文件上限为 1 GiB。结果摘要保存在 `data/output/web_agent_runs`，该目录已加入 Git 忽略规则。

## 当前分析流程

- **描述分析**：记录数、时间范围、采样间隔、缺失/重复情况、资产分组、关键指标分位数和按分钟趋势。
- **诊断分析**：驱动状态规则、跟随误差/转矩/动作时间异常筛查，并显示原始诊断位和 `DIAGNO` 供对照。
- **生命周期**：按当前观察窗内异常标记快照占比给出状态筛查分与提示标签；它不是可靠性概率或安全评级。
- **预测分析**：检查资产 ID、使用年龄和确认失效标签等数据条件；不满足时不会伪造 RUL 数值，并列出候选模型及数据缺口。
- **本地问答**：基于已计算的本地结果回答描述、诊断、生命周期和寿命准备度问题；原始数据不会发往外部模型。

## 数据解释边界

当前参数表提供 Tag、类型、样例和采样间隔，尚无设备诊断位/代码的语义映射。异常阈值是数据窗内的统计筛查阈值，需要按工况、产品、设备及动作阶段校准。持续异常按 100 ms 快照逐行显示，不能直接理解为独立故障数。

剩余寿命需要多台同类设备的长期使用年龄、删失状态、确认失效/更换事件和维护记录。当前 10,000 行文件只覆盖一个站点约 17 分钟，适合验证字段与工作流，不足以训练或验证 RUL。CSV 读取目前使用 Pandas 整表载入，1 GiB 是文件限制，不保证该大小在每台机器上都可用；超大 ClickHouse 导出仍需要按设备/时间分区或后续连接仓库分批查询。

## Bosch 工作台界面（2026-10-19）

界面直接沿用 `local_web_demo/DESIGN_REFERENCES.md` 中的内部演示设计：官方本地 Logo、Supergraphic 彩带、石墨灰导航栏、蓝色主操作、浅灰工作区、4px 控件圆角。素材复制自 `local_web_demo/web/assets/`，原文件保持不变，来源与内部使用说明保留在 `web/assets/BOSCH_ASSETS.md`。

- `web/style.css`：共享颜色、控件、分析结果和面板外观。
- `web/workbench-layout.css`：顶部栏、导航栏、数据栏、分析区域和 Agent 面板的响应式布局。
- `web/layout.js`：面板开关、窄屏抽屉、键盘焦点与 Escape、专注模式退出后恢复布局。
- 宽屏显示数据栏和 Agent；中等宽度保留数据栏、Agent 使用抽屉；小屏两者均使用抽屉，单次只展开一个。
- 重启服务后为新的空白会话，选择数据并点击“运行完整分析”。

本次检查：`node Web_Framework/source/integrations/servo_cylinder_agent/tests/layout.mjs` 通过；浏览器检查了 1440px / 390px 布局、真实样例分析、数据/Agent 抽屉及专注模式恢复。宽屏截图保存在 `data/output/ui_review/bosch-workbench.jpg`。


## ClickHouse API 数据源（2026-10-20）

在数据栏的“数据源类型”中选择 **ClickHouse API 数据库**，填写 HTTP/HTTPS API 地址、数据库、数据表、用户名和密码，再点击“检查连接并读取字段”。连接成功后选择 DateTime/DateTime64 时间字段、北京时间的开始/结束时间，可按站点字段精确筛选，然后运行完整分析。

接入标准 [ClickHouse HTTP API](https://clickhouse.com/docs/concepts/features/interfaces/http)，不是任意自定义 REST 网关。请求由本地 Python 服务发出，使用 `X-ClickHouse-User` / `X-ClickHouse-Key` 认证和 JSONEachRow 响应；HTTPS 使用系统证书校验。SQL 模板只提供读取，筛选值用参数绑定，查询使用 `readonly=2`；建议使用仓库已有的只读账号。若服务器账号策略禁止调整查询限制，连接检查会明确失败，需要数据库管理员配置允许的限制。

连接凭据只在当前服务进程内存中保存；不写浏览器存储、不写结果文件，也不自动读取仓库其他脚本中的账号密码。检查成功后网页清空密码框，后续使用不透明连接 ID；连接有效期一小时，过期或重启服务后需要重新检查。修改连接配置后需要重新填写密码。

为适配大量数据，查询必须限定时间范围（左闭右开）；单次最多 31 天、100,000 行（默认 10,000）、64 MiB，数据库执行限时 30 秒，并限制扫描行数。查询会多读一行检测超限，超过用户行数上限时拒绝分析，避免把截断数据当成完整范围。数据在限定范围内载入 Pandas 进行现有四类分析；此版本不代表已经实现跨月全量或流式模型训练。

数据库原始时间统一通过 Unix 毫秒转换成 UTC，页面仍按当前分析流程显示北京时间。连接只检查 `SELECT 1` 和目标表结构，真实数据库连通性需在能访问产线网络的电脑上验证。

检查命令（工作目录 `Web_Framework/source`）：

```sh
python -m unittest discover -s integrations/servo_cylinder_agent/tests -p 'test_clickhouse_*.py' -v
```

本次通过 12 项连接边界检查，以及本机模拟 ClickHouse HTTP → 网页 API → 共用分析流程的集成检查；集成检查也覆盖原 10,000 行 CSV 分析。未连接真实产线数据库。
