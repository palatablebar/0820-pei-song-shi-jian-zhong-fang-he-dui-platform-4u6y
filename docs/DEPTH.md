# 配送事件重放核对台规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 序号裁决 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 墓碑重放 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 水位复核 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 下游续取 | 按签发与接收事实交付回执 | `POST /api/deliveries` | `app/delivery/service.py` | `tests/test_delivery.py` |

## 交付规则

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| DEL-01 | 只交付已签发且对账一致的批次 | `app/delivery/service.py` | `tests/test_delivery.py::test_only_issued_reconciled_runs_are_delivered` |
| DEL-02 | 前序缺口停住，不越过未接收批次 | `app/delivery/service.py` | `tests/test_delivery.py::test_out_of_order_issue_stops_before_the_gap` |
| DEL-03 | 同一交接重试不新增回执 | `app/review/store.py` | `tests/test_delivery.py::test_retry_returns_same_receipt` |
| DEL-04 | 回执只追加，旧回执原样保留 | `app/review/store.py` | `tests/test_delivery.py::test_old_receipt_is_preserved` |
| DEL-05 | 续取数量与版本须与回执一致 | `app/delivery/service.py` | `tests/test_delivery.py::test_cursor_must_match_receipt` |
| DEL-06 | 补齐缺口后从原回执接着取 | `app/delivery/service.py` | `tests/test_delivery.py::test_catching_up_continues_from_the_original_cursor` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

按分区水位裁断，超过水位的消息待下个批次。同键同序号的不同事件阻断。删除保留墓碑序号，以便审查迟到写入。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`。
