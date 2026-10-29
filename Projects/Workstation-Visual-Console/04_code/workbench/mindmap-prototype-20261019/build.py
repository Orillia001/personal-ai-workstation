"""Build the selected A dark full-course mind-map prototype in the workbench shell."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import sys

root=Path(r'C:\Users\ok\Desktop\workstation')
here=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'Tools'))
from education_network import network_data
from obsidian_learning import course_progress

courses={}
for course in network_data(root)['courses']:
    courses[course['id']]={'graph':network_data(root,course['id']),'progress':course_progress(root,course['id'])}
data={'captured':datetime.now(timezone(timedelta(hours=8))).isoformat(),'courses':courses}
template=(here.parent/'layout-prototype.html').read_text(encoding='utf-8')
shell_hash=hashlib.sha256((here.parent/'layout-prototype.html').read_bytes()).hexdigest()
css=(here/'mindmap-dark.css').read_text(encoding='utf-8')
js=(here/'mindmap-dark.js').read_text(encoding='utf-8')
template=template.replace('<link rel="stylesheet" href="/workbench/education-network.css">','<style>'+css+'</style>')
payload=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
template=template.replace('<script src="/workbench/education-network.js"></script>',
                          '<script type="application/json" id="mindmap-data">'+payload+'</script><script>'+js+'</script>')
template=template.replace('const saveEnabled=!new URLSearchParams(location.search).has("smoke");','const saveEnabled=false;')
template=template.replace('    initializeWorkbench();','    state.view="project";state.project="university";state.child="machine";state.projectPaneOpen=false;initializeWorkbench();')
template=template.replace('<title>工作台 · Personal AI Workstation</title>','<title>课程思维导图 · 深色 A 版 Demo</title>')
template=template.replace('</head>','<meta name="mindmap-open-token" content="__MINDMAP_OPEN_TOKEN__"></head>')
(here/'mindmap-prototype.html').write_text(template,encoding='utf-8')
(here/'snapshot.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
(here/'build-receipt.json').write_text(json.dumps({'prototype':True,'production_shell_sha256':shell_hash,
    'course_count':len(courses),'default_course':'machine-design','selected_variant':'A-dark-full-map',
    'learning_mutations':False,'snapshot_at':data['captured']},ensure_ascii=False,indent=2),encoding='utf-8')
print('Demo built: selected A, dark full-course map; search and plain-text path; no learning mutations.')
