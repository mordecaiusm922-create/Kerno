c = open("api.py", encoding="utf-8").read()
old = '@app.get("/dashboard", response_class=HTMLResponse)'
new = '@app.get("/terminal", response_class=HTMLResponse)\ndef get_terminal():\n    return open("terminal.html", encoding="utf-8").read()\n\n@app.get("/dashboard", response_class=HTMLResponse)'
if old in c:
    c = c.replace(old, new, 1)
    open("api.py", "w", encoding="utf-8").write(c)
    print("OK")
else:
    print("NOT FOUND")