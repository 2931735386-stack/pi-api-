import ast, sys

files = ['app.py', 'analytics.py', 'dashboard_widgets.py', 'dashboard_tab.py']
ok = True
for f in files:
    try:
        src = open(f, encoding='utf-8').read()
        ast.parse(src)
        print(f'OK: {f}')
    except SyntaxError as e:
        print(f'ERROR in {f}: line {e.lineno}: {e.msg}')
        ok = False

sys.exit(0 if ok else 1)
