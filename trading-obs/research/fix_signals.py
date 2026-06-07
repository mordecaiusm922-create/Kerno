content = open("api.py", encoding="utf-8").read()
lines = content.split("\n")

# Encontrar inicio del primer /signals (linea 285, index 284)
start = None
end = None
for i, l in enumerate(lines):
    if "@app.get(\"/signals\")" in l and start is None:
        start = i
    elif "@app.get(" in l and start is not None and end is None:
        end = i
        break

if start is None or end is None:
    print(f"ERROR: start={start} end={end}")
else:
    print(f"Eliminando lineas {start+1} a {end} ({end-start} lineas)")
    print("Primer endpoint:")
    print("\n".join(lines[start:start+5]))
    new_lines = lines[:start] + lines[end:]
    open("api.py", "w", encoding="utf-8").write("\n".join(new_lines))
    print("OK: primer /signals eliminado")