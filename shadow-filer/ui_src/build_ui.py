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
pages = '\n'.join(strip(p) for p in ('cleanup_page.js', 'search_page.js', 'settings_page.js', 'inbox_page.js'))
reps = [
    ('const w1=["overview","predictions","log","system","settings"]',
     'const w1=["overview","inbox","search","predictions","cleanup","log","system","settings"]'),
    ('const K1=[{id:"overview",label:"Overview",icon:i1},{id:"predictions",label:"Predictions",icon:s1},',
     pages + '\nconst K1=[{id:"overview",label:"Overview",icon:i1},{id:"inbox",label:"Inbox",icon:SFinboxIcon},'
             '{id:"search",label:"Search",icon:SFsearchIcon},'
             '{id:"predictions",label:"Predictions",icon:s1},{id:"cleanup",label:"Cleanup",icon:SFtrash},'),
    ('s==="predictions"&&f.jsx(ay,{}),',
     's==="inbox"&&f.jsx(SFinbox,{}),s==="search"&&f.jsx(SFsearch,{}),s==="predictions"&&f.jsx(ay,{}),s==="cleanup"&&f.jsx(SFcleanup,{}),'),
    ('s==="settings"&&f.jsx(fy,{})', 's==="settings"&&f.jsx(SFsettings,{})'),
    ('Shadow mode — never moves, renames or deletes anything',
     'Suggest mode — files move only when you click File it; deletes only what you confirm'),
]
for a, b in reps:
    assert src.count(a) == 1, a
    src = src.replace(a, b)
# Fixed file name, overwritten on every build (no stale copies pile up); the content hash goes in the URL
# so browsers still pick up a new build despite long-lived caching.
name = 'index-sfc.js'
version = hashlib.sha256(src.encode()).hexdigest()[:8]
open('ui_dist/assets/' + name, 'w', encoding='utf-8').write(src)
idx = open('ui_src/base/index.html', encoding='utf-8').read().replace('index-BoLOatoI.js', f'{name}?v={version}')
open('ui_dist/index.html', 'w', encoding='utf-8').write(idx)
print(name, version)
