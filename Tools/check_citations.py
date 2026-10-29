from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime

project = Path(sys.argv[1]).resolve()
bib = project / '02_literature/references.bib'
if not bib.is_file():
    sys.exit('PENDING: Export Zotero items using Better BibTeX to ' + str(bib))
text = bib.read_text(encoding='utf-8-sig')
keys = [m.group(2).strip() for m in re.finditer(r'@([A-Za-z]+)\s*[{(]\s*([^,\s]+)\s*,', text) if m.group(1).lower() not in {'comment', 'string', 'preamble'}]
if not keys:
    sys.exit('FAIL: No bibliography entries detected.')
key = keys[0]
if not re.fullmatch(r'[A-Za-z0-9_:.+/-]+', key):
    sys.exit('FAIL: First citation key requires manual inspection; no source files changed.')
out = project / '09_output' / ('citation-check-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
out.mkdir(parents=True, exist_ok=False)
source = out / 'citation-check.qmd'
source.write_text('---\ntitle: "Citation integration check"\nbibliography: "../../02_literature/references.bib"\n---\n\nTest citation: [@' + key + '].\n\n# References\n\n::: {#refs}\n:::\n', encoding='utf-8')
for fmt in ('html', 'docx'):
    run = subprocess.run(['quarto', 'render', str(source), '--to', fmt], capture_output=True, text=True, encoding='utf-8', errors='replace')
    log = run.stdout + run.stderr
    (out / (fmt + '.log')).write_text(log, encoding='utf-8')
    if run.returncode or not source.with_suffix('.' + fmt).is_file() or re.search(r'citation .* not found', log, re.I):
        sys.exit('FAIL: Inspect ' + str(out / (fmt + '.log')))
print('PASS: HTML and DOCX rendered using citation ' + key + ': ' + str(out))
