from flask import jsonify

LABELS = {
    "FILE_TOO_LARGE": "文件超过 256 KiB",
    "FILE_EMPTY": "文件没有内容",
    "FILE_BLANK": "文件只有空白",
    "HEADER_ONLY": "文件只有标题行",
    "HEADER_MISMATCH": "列名与字段字典不一致",
    "ENCODING_INVALID": "请使用 UTF-8 CSV",
    "CSV_MALFORMED": "CSV 引号或行格式异常",
    "ROW_LIMIT": "文件超过 2000 行",
    "FILE_REQUIRED": "请选择 CSV 文件",
    "RUN_NOT_FOUND": "批次不存在",
    "REVIEW_FIELDS": "请填写 3 至 200 字复核意见",
    "STALE_REVIEW": "批次已更新，请刷新",
    "RUN_FINALIZED": "批次已签发",
    "UNRESOLVED_ISSUES": "存在待处理差异",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "处理阶段不存在",
    "DELIVERY_FIELDS": "请以 JSON 提交交接号",
    "HANDOFF_REQUIRED": "请填写交接号",
    "HANDOFF_INVALID": "交接号只能使用字母、数字、点、横线、下划线和冒号",
    "RECEIPT_NOT_FOUND": "回执不存在",
    "RECEIPT_STALE": "回执已不是最新交接，请从最新回执续取",
    "RECEIPT_MISMATCH": "续取的数量或版本与回执不一致",
    "RECEIPT_CORRUPT": "回执内容校验失败",
    "RECEIPT_CONFLICT": "该位置已被另一份回执占用",
}


def response(error):
    code = error.code
    status = (
        404
        if code in {"RUN_NOT_FOUND", "SAMPLE_UNKNOWN", "STAGE_UNKNOWN", "RECEIPT_NOT_FOUND"}
        else (
            409
            if code
            in {
                "STALE_REVIEW",
                "RUN_FINALIZED",
                "UNRESOLVED_ISSUES",
                "RECEIPT_STALE",
                "RECEIPT_MISMATCH",
                "RECEIPT_CORRUPT",
                "RECEIPT_CONFLICT",
            }
            else 413 if code == "FILE_TOO_LARGE" else 422
        )
    )
    return jsonify(code=code, message=LABELS.get(code, code)), status
