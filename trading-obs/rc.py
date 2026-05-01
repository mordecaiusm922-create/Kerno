content = open('api.py', encoding='utf-8').read()
idx = content.find('def _classify')
print(content[idx:idx+600])
