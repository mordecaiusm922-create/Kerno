content = open('api.py', encoding='utf-8').read()

# Agregar arranque del validator como thread en startup
old_startup_end = '    print("[DB] Kerno inicializado'
idx = content.find(old_startup_end)
line_end = content.find('\n', idx)

validator_start = '''
    # Arrancar validator en background
    import threading
    from validator import validator_loop
    t = threading.Thread(target=validator_loop, daemon=True)
    t.start()
    print("[validator] thread iniciado")'''

content = content[:line_end] + validator_start + content[line_end:]
open('api.py', 'w', encoding='utf-8').write(content)
print('OK: validator thread registrado en startup')
