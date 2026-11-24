# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。

## 下游续取

`POST /api/deliveries` 接收 JSON：`handoff` 必填，是本次交接的唯一标识；可选 `receipt`、`count`、`version` 指向上一份回执并核对续取位置。返回该交接的回执。

- 交付顺序按批次登记顺序。批次只有在已签发（`APPROVED`）且对账一致（`balance.releasable`）时才会交付。
- 登记顺序中出现尚未签发的批次时，交付停在该缺口之前，回执返回 `BLOCKED`、`blocked` 指出缺口，且不落库（`id` 为 `null`）。没有新批次可交付时返回 `EMPTY`。
- 缺口补齐后，用原回执的 `id` 作为 `receipt` 续取，新回执从该回执的位置之后继续。
- 同一 `handoff` 重试返回已落库的同一份回执，不新增。传入非最新回执返回 409 `RECEIPT_STALE`；`count`/`version` 与回执不符返回 409 `RECEIPT_MISMATCH`。
- 回执只追加：`GET /api/deliveries` 列出最近 50 份回执头，`GET /api/deliveries/<id>` 取回原样回执。每份回执带 `count`（累计数量）、`version`（累计摘要）和 `delivered`（本段交付的批次），可用于校验续取的数量与版本。
