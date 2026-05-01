content = open('api.py', encoding='utf-8').read()
idx = content.find('enriched.append(d)')
print(content[idx-300:idx+100])
