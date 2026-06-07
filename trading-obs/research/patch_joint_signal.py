content = open("api.py", encoding="utf-8").read()

# Agregar _load_stage1 despues de _load_model
old_load = '''def _load_model():
    global _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES
    if _KERNO_MODEL is None:
        try:
            with open("kerno_model.pkl", "rb") as f:
                data = _pickle.load(f)
            _KERNO_MODEL   = data["model"]
            _KERNO_SCALER  = data["scaler"]
            _KERNO_FEATURES = data["features"]'''

new_load = '''_STAGE1_MODEL = None
_STAGE1_SCALER = None
_STAGE1_FEATURES = None

def _load_stage1():
    global _STAGE1_MODEL, _STAGE1_SCALER, _STAGE1_FEATURES
    if _STAGE1_MODEL is None:
        try:
            with open("kerno_stage1.pkl", "rb") as f:
                data = _pickle.load(f)
            _STAGE1_MODEL   = data["model"]
            _STAGE1_SCALER  = data["scaler"]
            _STAGE1_FEATURES = data["features"]
        except Exception as e:
            print(f"[stage1] error: {e}")
    return _STAGE1_MODEL, _STAGE1_SCALER, _STAGE1_FEATURES

def _load_model():
    global _KERNO_MODEL, _KERNO_SCALER, _KERNO_FEATURES
    if _KERNO_MODEL is None:
        try:
            with open("kerno_model.pkl", "rb") as f:
                data = _pickle.load(f)
            _KERNO_MODEL   = data["model"]
            _KERNO_SCALER  = data["scaler"]
            _KERNO_FEATURES = data["features"]'''

if old_load in content:
    content = content.replace(old_load, new_load, 1)
    open("api.py", "w", encoding="utf-8").write(content)
    print("OK: _load_stage1 agregado")
else:
    print("NOT FOUND")
    idx = content.find("def _load_model")
    print(repr(content[idx:idx+100]))