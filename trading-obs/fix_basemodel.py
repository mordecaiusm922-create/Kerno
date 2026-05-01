content = open('api.py', encoding='utf-8').read()
if 'from pydantic import BaseModel' not in content:
    content = content.replace('from fastapi', 'from pydantic import BaseModel\nfrom fastapi', 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: BaseModel importado')
else:
    print('ya existe, revisando...')
    idx = content.find('BaseModel')
    print(content[idx-50:idx+50])
