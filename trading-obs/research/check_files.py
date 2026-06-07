import os
files = ['api.py', 'kerno_model_final.pkl', 'kerno_stage1.pkl', 
         'validator.py', 'terminal.html', 'patch_joint_signal.py']
for f in files:
    print(f, "OK" if os.path.exists(f) else "MISSING")