COLUMNS = ("partition", "entity", "seq", "quantity")
KINDS = ("upsert", "delete", "watermark", "expected")
PROJECT = {
    "name": "配送事件重放核对台",
    "actor": "配送数仓管道值班员",
    "stages": [
        ("intake", "样例采信"),
        ("prepare", "序号裁决"),
        ("calculate", "墓碑重放"),
        ("policy", "水位复核"),
        ("balance", "运行对账"),
    ],
    "chart": "事件重放结果",
}
