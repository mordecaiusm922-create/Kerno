content = open('api.py', encoding='utf-8').read()

dashboard = '''
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    return open("dashboard.html", encoding="utf-8").read()
'''

# Insertar antes del ultimo bloque
content = content + dashboard
open('api.py', 'w', encoding='utf-8').write(content)
print('OK: /dashboard agregado')
