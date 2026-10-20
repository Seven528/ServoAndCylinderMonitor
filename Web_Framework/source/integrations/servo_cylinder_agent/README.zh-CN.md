# 伺服与气缸分析 Agent

这是 `Web_Framework` 中独立运行的本地分析集成。它复用该框架“小型 Python HTTP 服务 + 原生 HTML/CSS/ES Modules”模式，不依赖 PCB 原生引擎、MCP SDK 或外部模型。

## 启动

在 VS Code 打开项目根目录的 `main_web.py`，选择已安装 `pandas`、`numpy`、`openpyxl` 的 Python 解释器，点击右上角 **Run Python File**。脚本会启动服务并自动打开浏览器；不需要命令行参数，不依赖终端当前目录。

保持该终端运行；按 **Ctrl+C** 停止。重复运行时，如同一端口已有本项目服务，会打开现有服务；如果端口被其他程序占用，会提示修改 `main_web.py` 中的 `WEB_PORT`。更新后需要重启时，应先在原终端停止服务。

也可从 `Web_Framework/source` 执行：

```sh
python -m integrations.servo_cylinder_agent.server --port 8890
```

访问 `http://127.0.0.1:8890`。服务只绑定本机回环地址。CSV / XLSX 文件放在项目的 `data/input` 目录后，可在网页数据源下拉框选择；也可直接选择文件或填写本机绝对路径，应用不限制文件大小。结果摘要保存在 `data/output/web_agent_runs`，该目录已加入 Git 忽略规则。

## 当前分析流程

- **描述分析**：记录数、时间范围、采样间隔、缺失/重复情况、资产分组、关键指标精确分位数和覆盖完整时间窗的自适应聚合趋势。
- **诊断分析**：驱动状态规则、跟随误差/转矩/动作时间异常筛查，并显示原始诊断位和 `DIAGNO` 供对照。
- **生命周期**：按当前观察窗内异常标记快照占比给出状态筛查分与提示标签；它不是可靠性概率或安全评级。
- **预测分析**：检查资产 ID、使用年龄和确认失效标签等数据条件；不满足时不会伪造 RUL 数值，并列出候选模型及数据缺口。
- **本地问答**：基于已计算的本地结果回答描述、诊断、生命周期和寿命准备度问题；原始数据不会发往外部模型。

## 数据解释边界

当前参数表提供 Tag、类型、样例和采样间隔，尚无设备诊断位/代码的语义映射。异常阈值是数据窗内的统计筛查阈值，需要按工况、产品、设备及动作阶段校准。持续异常按 100 ms 快照逐行显示，不能直接理解为独立故障数。

剩余寿命需要多台同类设备的长期使用年龄、删失状态、确认失效/更换事件和维护记录。当前 10,000 行文件只覆盖一个站点约 17 分钟，适合验证字段与工作流，不足以训练或验证 RUL。CSV、XLSX 和 ClickHouse 均分批读取，完整数据写入临时 SQLite 进行磁盘统计，避免整表载入 Pandas。应用不截取数据前缀作为全量分析。

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

查询采用用户选定的时间范围（左闭右开），应用不限制时间跨度、扫描行数、结果行数或数据字节数，SQL 不附加 LIMIT。请求将 max_rows_to_read、max_bytes_to_read、对应 leaf 限制、max_result_rows、max_result_bytes、max_execution_time 和 max_execution_time_leaf 设置为 0。300 秒是网络无响应超时，不是查询总时长上限。

数据库原始时间统一通过 UTC 字符串转换成 UTC，页面仍按当前分析流程显示北京时间。连接只检查 `SELECT 1` 和目标表结构，真实数据库连通性需在能访问产线网络的电脑上验证。

检查命令（工作目录 `Web_Framework/source`）：

```sh
python -m unittest discover -s integrations/servo_cylinder_agent/tests -p 'test_clickhouse_*.py' -v
```

本次通过 12 项连接边界检查，以及本机模拟 ClickHouse HTTP → 网页 API → 共用分析流程的集成检查；集成检查也覆盖原 10,000 行 CSV 分析。未连接真实产线数据库。


## 本地文件、诊断与日志（2026-10-20）

- 本地数据支持“选择 CSV / XLSX 文件”、输入完整绝对路径，或选择项目目录文件。浏览器选择的文件副本只传给本机服务，保存在会话临时目录，原文件保持不变。服务重启后须重新选择。
- XLSX 可选择工作表；首行为参数字段名。CSV 支持 UTF-8 与 GB18030。CSV / XLSX 不设文件大小、展开大小或分析行数上限。浏览器文件以流式方式写入本机临时目录；超大文件建议直接填写本机绝对路径，避免额外复制。
- ClickHouse 查询现在只读取分析用字段，时间统一通过 UTC 字符串传回本机转换；时间范围仍采用参数绑定。已移除数据库侧全量排序，取完后在本机排序。扫描/时间/内存/权限错误会显示数据库异常码及对应处理提示，无法仅凭原有通用 HTTP 500 确认真实服务器的根因。
- `main_web.py` 使用项目可解析的静态导入路径，支持 VS Code 直接运行，不依赖修改 `sys.path` 或固定解释器。
- Web 直接使用 `src/logger.py` 的 `Logger`，该文件未修改；共享实例与日志脱敏位于 `src/web_logging.py`。日志位置为 `data/output/logger/YYYYMMDD.log`，按原 Logger 的规则每日追加 UTF-8 日志。
- 日志覆盖启动/停止、主程序运行、任务排队和完成、文件读取、ClickHouse 连接与查询失败。错误记录经过脱敏的异常和调用栈，不记录密码、会话令牌、原始查询响应、用户问答或数据明细。


## 输入区语音与模型选择（2026-10-20）

输入框下方新增模型菜单、麦克风与发送按钮；`Ctrl/Cmd+Enter` 发送，单独 Enter 换行。语音只填入文字，不自动提交。输入区外观参照 `local_web_demo` 的模型选择和听写组件；Codex stdio 桥接源码从该框架的 `codex_bridge.py` 适配，原模块保持不变。

### 模型

- 默认“本地统计问答”，无需 Codex，不发送数据到外部模型。
- 点击模型名称 → “连接本机 Codex”，读取本机已安装、已登录 Codex 的模型列表，再选择模型、推理强度和响应速度。无固定虚构列表；列表由本机运行程序返回，实际调用仍受账号和网络限制。
- 未找到 Codex 时可设置环境变量 `SERVO_AGENT_CODEX_BIN` 为可执行文件位置；启动脚本依旧使用用户自己选择的 Python，不固定解释器。
- 外部模型只收到本次问题和去除文件名、资产标识、逐行事件、参数示例后的统计摘要；发送前需在页面勾选确认。模型不直接访问源文件、ClickHouse 或项目目录，临时会话不写入聊天历史。
- 所选模型、推理强度和速度会透传到真实调用，并核对运行程序返回值。失败会明确提示，不自动切换模型或用本地规则冒充模型回答。
- 参考 [OpenAI Codex App Server 文档](https://learn.chatgpt.com/docs/app-server)，使用 `model/list`、`thread/start`、`turn/start`，不是模拟选项。

### 语音

- 麦克风按钮打开听写设置，支持中文，最长 60 秒、最多填入 1000 字。
- 本机离线模式要求浏览器支持 `SpeechRecognition.processLocally` 和中文离线语言包；下载语言包必须手动点击，不自动安装。
- 浏览器语音服务可能联网，必须单独选择并勾选音频发送确认，不从离线模式静默切换。
- 浏览器本身控制麦克风授权。拒绝授权、没有麦克风、语言包缺失或网络失败会显示具体状态。关闭面板、切换到后台、Escape 都会取消当前识别；再点麦克风可以停止听写。
- 没有 Web Speech API 的浏览器显示系统听写提示（Windows Win+H、Mac 系统听写），不声称语音可用。
- 音频由浏览器语音识别处理，应用后端不上传或保存音频。请按 [Web Speech API 支持说明](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API) 选择识别方式。

本次检查：26 项 Python 回归检查、语音状态与授权边界检查、布局检查通过；并使用纯虚构摘要完成一次真实 Codex 模型调用。未在自动检查中启动麦克风或下载语言包，真实录音由用户点击后授权。


## 全量大数据处理（2026-10-20）

- 每批默认读取 10,000 条只是内部缓冲批次大小，所有批次都会处理，不是输入行数限制。
- 原始记录写入临时磁盘数据库；全量统计重复行、分位数、异常数量，并以同一资产及工况的全窗中位数 / MAD 建立基准，不在每批单独拟合。中位数、P95 与 MAD 在磁盘上精确计算。
- 趋势图使用覆盖整个时间范围的自适应时间桶；界面仅预览前 100 个资产及最新 100 条异常明细，汇总数字仍覆盖全部记录。结果的 processing.rows_processed 和 source_truncated 可核对处理范围。
- 任务过程中显示累计读取数量和统计阶段，可以点击取消；取消或读取失败不会发布部分结果。磁盘临时统计文件在任务退出时删除。
- 不设应用层上限不等于无限硬件资源。全量精确分位数需要磁盘空间、排序时间；XLSX 的共享字符串等元数据仍由 openpyxl 管理。耗时取决于数据量和本机资源。
- 若仍返回 Code 158，说明 ClickHouse 账号、集群叶节点、设置约束或代理仍有额外限制，需要管理员调整对应策略；网页不能绕过数据库权限。可参考 [ClickHouse 查询复杂度限制](https://clickhouse.com/docs/concepts/features/configuration/settings/query-complexity)。

新增回归检查覆盖 120,001 条输入、跨批次重复与异常基准、按资产计算健康分以及完整时间窗趋势。真实产线 ClickHouse 仍需在可访问该数据库的电脑上运行确认。
