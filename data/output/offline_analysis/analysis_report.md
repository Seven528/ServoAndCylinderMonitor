# 伺服与气缸离线监控分析

- 输入文件：`MECN_MOE6_RUNTIMEPARAMMONITOR_WEBSCADA_JSON_PROCESSED_V02_20261016.csv`
- 数据行数：10,000
- 时间范围：0.28 小时
- 识别资产组数：1
- 重复行：0
- 异常筛查记录：1,748
- 参数字典记录数：31；字段：PartName, TagName, Type, Value(example), Sampling interval。

## 资产状态摘要

| asset_key | records | first_timestamp | last_timestamp | acttorque_median | acttorque_p95 | acttorque_max | actvel_median | actvel_p95 | actvel_max | acttime_ms_median | acttime_ms_p95 | acttime_ms_max | movetotbastime_ms_median | movetotbastime_ms_p95 | movetotbastime_ms_max | movetoworktime_ms_median | movetoworktime_ms_p95 | movetoworktime_ms_max | movementcounter_median | movementcounter_p95 | movementcounter_max | diagnostic_assertions | screened_records | screened_record_rate | lifecycle_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BS / LidPalletizer / FA14 / ST401 / RunTimeStatus.ME/MOE6-CN | 10000 | 2026-09-13 00:17:57.331000+08:00 | 2026-09-13 00:34:41.608000+08:00 | 16.0 | 17.7 | 32.7 | 0.0 | 0.061 | 231.628 | 2250.0175 | 5466.0307 | 13980.0847 | 1422.0119 | 1428.0173 | 1440.0155 | 1956.0144 | 1974.0132 | 1980.0146 | 203104.0 | 203180.0 | 203193 | 1605 | 1748 | 0.1748 | needs_review |

## 参数字典

| PartName | TagName | Type | Value(example) | Sampling interval |
| --- | --- | --- | --- | --- |
| Cylinder | MoveToBasTime | LTIME | LTIME#1s410ms4us700ns | 100ms |
| Cylinder | MoveToWorkTime | LTIME | LTIME#1s910ms998us800ns | 100ms |
| Cylinder | MovementCounter | LWORD | 3 | 100ms |
| Servo | ActPos | LREAL | 440 | 100ms |
| Servo | ActPosEc1 | LREAL | 440 | 100ms |
| Servo | ActPosEc2 | LREAL | 0 | 100ms |
| Servo | ActVel | LREAL | 0 | 100ms |
| Servo | ActTorque | LREAL | 15.8 | 100ms |
| Servo | AxisInReference | BOOL | True | 100ms |
| Servo | StandStill | BOOL | True | 100ms |
| Servo | DriveConst | BOOL | 0 | 100ms |
| Servo | Accelerating | BOOL | 0 | 100ms |
| Servo | Decelerating | BOOL | 0 | 100ms |
| Servo | Class1Diag | BOOL | 0 | 100ms |
| Servo | Class2Diag | BOOL | 0 | 100ms |
| Servo | Class3Diag | BOOL | True | 100ms |
| Servo | DriveEnabled | BOOL | True | 100ms |
| Servo | DriveReadyForOp | BOOL | 0 | 100ms |
| Servo | DriveReadyForMovement | BOOL | True | 100ms |
| Servo | DiagNo | DWORD | 655713 | 100ms |
| Servo | ActTime | LTIME | LTIME#2s130ms31us300ns | 100ms |
| Servo | AvgTime | LTIME | LTIME#2s843ms997us388ns | 100ms |
| Servo | MinTime | LTIME | LTIME#29ms992us300ns | 100ms |
| Servo | MaxTime | LTIME | LTIME#9s666ms115us100ns | 100ms |
| Servo | TotTime | LTIME | LTIME#5h34m58s529ms548us | 100ms |
| Servo | Samples | LWORD | 7067 | 100ms |
| Servo | Exeute | BOOL | 0 | 100ms |
| Servo | Speed | LREAL | 250 | 100ms |
| Servo | TargetPos | LREAL | -23.5 | 100ms |
| Servo | Acc | LREAL | 1000 | 100ms |
| Servo | Dec | LREAL | 700 | 100ms |

## 异常筛查信号

| flag | records |
| --- | --- |
| SERVO_TORQUE_OUTLIER | 1655 |
| CLASS3DIAG_ASSERTED | 1605 |
| SERVO_ACTTIME_OUTLIER | 859 |

## 数据质量与建模边界

- 时间戳中位采样间隔：0.100 秒。
- 时间戳间隔 P95：0.201 秒。
- 气缸动作时间和伺服反馈值来自周期快照，异常表示相对本次样本分布偏离。
- 同一异常连续多个 100 ms 快照会逐行计数；上表是记录数，不是独立故障次数。
- CLASS1/2/3DIAG 的 TRUE 仅按状态位筛出，尚未用设备手册确认其告警语义；请先对照诊断位定义和 DIAGNO 编码表。
- 当前文件只有有限时间窗，缺少确认故障、维修与换件标签；RUL 暂不建模。

## 解读限制

- Outlier flags are statistical screening signals based on this export window, not confirmed faults.
- Lifecycle labels are heuristic and do not represent a calibrated failure probability.
- RUL is not estimated: this short snapshot does not provide confirmed failures, maintenance outcomes, or enough degradation history.

筛查明细见 `anomaly_events.csv`；全部转换数据见 `enriched_data.csv`。