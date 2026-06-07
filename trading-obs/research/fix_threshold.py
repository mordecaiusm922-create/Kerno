content = open('api.py', encoding='utf-8').read()
content = content.replace(
    'if intel.get("confidence", 0) >= 0.50 and',
    'if intel.get("confidence", 0) >= 0.34 and',
    1
)
open('api.py', 'w', encoding='utf-8').write(content)
print('OK: threshold de recording bajado a 0.34')
