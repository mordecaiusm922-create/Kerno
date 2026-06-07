c = open("api.py", encoding="utf-8").read()
old = '"action":        "FILTER_IN",\n        })'
new = '"action":        "FILTER_IN",\n            "drivers":      drivers,\n        })'
if old in c:
    c = c.replace(old, new, 1)
    open("api.py", "w", encoding="utf-8").write(c)
    print("OK")
else:
    print("NOT FOUND")
    idx = c.find("FILTER_IN")
    print(repr(c[idx-5:idx+50]))