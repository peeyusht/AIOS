"""Build the UI: inject the Cleanup, Search and Settings pages (ui_src/*.js) into the base bundle
(ui_src/base, the original Vite build) and write ui_dist/. Run:  python ui_src/build_ui.py"""
import glob
import hashlib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(os.path.dirname(HERE))  # the shadow-filer folder
for f in glob.glob('ui_dist/assets/index-sfc*.js'):
    os.remove(f)
src = open('ui_src/base/index-BoLOatoI.js', encoding='utf-8').read()
strip = lambda p: re.sub(r'/\*.*?\*/', '', open(os.path.join('ui_src', p), encoding='utf-8').read(), flags=re.S)
pages = strip('cleanup_page.js') + '\n' + strip('search_page.js') + '\n' + strip('settings_page.js')
reps = [
    ('const w1=["overview","predictions","log","system","settings"]',
     'const w1=["overview","search","predictions","cleanup","log","system","settings"]'),
    ('const K1=[{id:"overview",label:"Overview",icon:i1},{id:"predictions",label:"Predictions",icon:s1},',
     pages + '\nconst K1=[{id:"overview",label:"Overview",icon:i1},{id:"search",label:"Search",icon:SFsearchIcon},'
             '{id:"predictions",label:"Predictions",icon:s1},{id:"cleanup",label:"Cleanup",icon:SFtrash},'),
    ('s==="predictions"&&f.jsx(ay,{}),',
     's==="search"&&f.jsx(SFsearch,{}),s==="predictions"&&f.jsx(ay,{}),s==="cleanup"&&f.jsx(SFcleanup,{}),'),
    ('s==="settings"&&f.jsx(fy,{})', 's==="settings"&&f.jsx(SFsettings,{})'),
    ('Shadow mode — never moves, renames or deletes anything',
     'Shadow mode — never moves or renames; deletes only what you confirm on Cleanup'),
]
for a, b in reps:
    assert src.count(a) == 1, a
    src = src.replace(a, b)
name = f'index-sfc{hashlib.sha256(src.encode()).hexdigest()[:8]}.js'
open('ui_dist/assets/' + name, 'w', encoding='utf-8').write(src)
idx = open('ui_src/base/index.html', encoding='utf-8').read().replace('index-BoLOatoI.js', name)
open('ui_dist/index.html', 'w', encoding='utf-8').write(idx)
print(name)
