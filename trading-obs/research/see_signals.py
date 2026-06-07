c = open("api.py", encoding="utf-8").read()
idx = c.find("get_signals_ml")
print(c[idx:idx+1500])