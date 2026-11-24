EXPECTED = {
    "0001": (4, 70, "READY"),
    "0002": (1, 0, "READY"),
    "0003": (0, None, "SOURCE_CONFLICT"),
    "0004": (2, 15, "MISMATCH"),
}
EVIDENCE = {
    "0001": {"live": {"1/2": 70}, "tombstones": {"1/1": 4}},
    "0002": {"live": {}, "tombstones": {"2/1": 1}},
}
