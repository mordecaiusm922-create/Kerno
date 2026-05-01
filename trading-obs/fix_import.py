content = open('api.py', encoding='utf-8').read()

old = 'from fastapi'
new = 'from fastapi.responses import HTMLResponse\nfrom fastapi'

if old in content:
    content = content.replace(old, new, 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: HTMLResponse importado')
else:
    print('ERROR')
