from pathlib import Path
import json

HERE=Path(__file__).resolve().parent
package=json.loads((HERE/'package-data.json').read_text())
# Escape script-closing characters in all embedded source files.
encoded=json.dumps(package,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
html=(HERE/'page.template.html').read_text().replace('__REPLAY_DATA__',encoded)
(HERE/'dist/index.html').write_text(html)
print('Built self-contained offline page:',len(html.encode()),'bytes')
