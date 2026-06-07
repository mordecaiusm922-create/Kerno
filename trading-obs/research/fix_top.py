content = open('api.py', encoding='utf-8').read()
header = """from pydantic import BaseModel
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Annotated
import threading, time

"""
if 'from pydantic import BaseModel' not in content:
    content = header + content
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: imports agregados al inicio')
else:
    print('ya existe')
