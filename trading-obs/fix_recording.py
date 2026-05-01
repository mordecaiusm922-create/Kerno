content = open('api.py', encoding='utf-8').read()
content = content.replace(
    'if intel.get("confidence", 0) >= 0.34 and',
    'if intel.get("confidence", 0) >= 0.62 and intel.get("bucket") in ("MEDIUM","LARGE","EXTREME") and',
    1
)
open('api.py', 'w', encoding='utf-8').write(content)
print('OK: solo registra MEDIUM+')
