c = open("api.py", encoding="utf-8").read()
old = '"drivers":      drivers,'
new = '"drivers":      drivers,\n            "p_tradeable":  round(p_tradeable, 3),\n            "joint_score":  joint,'
if old in c:
    c = c.replace(old, new, 1)
    open("api.py", "w", encoding="utf-8").write(c)
    print("OK")
else:
    print("NOT FOUND")
    idx = c.find("drivers")
    print(repr(c[idx:idx+100]))