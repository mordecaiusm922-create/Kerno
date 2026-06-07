content = open('api.py', encoding='utf-8').read()

old_map = '''_EDGE_MAP = {
    "BTCUSDT": {
        "MEDIUM":  ("REV_EDGE",  0.66, 0.34),
        "LARGE":   ("CONT_EDGE", 0.28, 0.72),
    },
    "ETHUSDT": {
        "SMALL":   ("REV_EDGE",  0.61, 0.39),
        "LARGE":   ("CONT_EDGE", 0.40, 0.60),
        "EXTREME": ("CONT_EDGE", 0.25, 0.75),
    },
}'''

new_map = '''_EDGE_MAP = {
    "BTCUSDT": {
        "SMALL":   ("REV_EDGE",  0.63, 0.37),
        "MEDIUM":  ("REV_EDGE",  0.73, 0.27),
        "EXTREME": ("CONT_EDGE", 0.13, 0.87),
    },
    "ETHUSDT": {
        "LARGE":   ("CONT_EDGE", 0.30, 0.70),
        "EXTREME": ("CONT_EDGE", 0.29, 0.71),
    },
}'''

if old_map in content:
    content = content.replace(old_map, new_map, 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: _EDGE_MAP calibrado con datos reales')
else:
    print('ERROR: texto no encontrado')
