"""Exercise the real preview launcher and binding resolver without repeatedly opening apps."""
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import threading
import preview
import obsidian_learning

def main():
    here=Path(__file__).resolve().parent
    snapshot=json.loads((here/'snapshot.json').read_text(encoding='utf-8'))
    checks=[]
    opened=[]
    original=obsidian_learning.os.startfile
    obsidian_learning.os.startfile=opened.append
    server=preview.create_server(0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    headers={'Content-Type':'application/json','Origin':base,'X-Mindmap-Token':server.open_token}
    def check(name,passed):
        checks.append({'name':name,'pass':bool(passed)})
    def post(data,changes=None,path='/api/education/open-note'):
        request=Request(base+path,data=json.dumps(data).encode('utf-8'),headers={**headers,**(changes or {})},method='POST')
        try:
            response=urlopen(request,timeout=10)
        except HTTPError as error:
            response=error
        return response.status,response.read()
    try:
        with urlopen(base+'/workbench',timeout=10) as response:
            html=response.read().decode('utf-8')
            check('预览注入打开令牌且保留客户端占位检测',f'content="{server.open_token}"' in html and "token==='__MINDMAP_OPEN_TOKEN__'" in html)
        for course,data in snapshot['courses'].items():
            node=next((n for n in data['graph']['nodes'] if n['kind']!='module'),data['graph']['nodes'][0])
            expected=next(n for n in data['progress']['nodes'] if n['id']==node['id'])['obsidian_uri']
            status,body=post({'course':course,'node_id':node['id']})
            check(f'{course}按知识点绑定解析对应笔记',status==200 and json.loads(body)['requested'] and opened[-1]==expected)
        count=len(opened)
        valid={'course':'machine-design','node_id':'MD-C-static'}
        check('拒绝外站发起打开',post(valid,{'Origin':'https://example.com'})[0]==403)
        check('拒绝缺少有效令牌',post(valid,{'X-Mindmap-Token':''})[0]==403)
        check('不接受任意路径或URI',post({**valid,'path':'C:/other.md'})[0]==400)
        check('拒绝非字符串参数',post({'course':[],'node_id':'MD-C-static'})[0]==400)
        check('无对应知识点时不启动应用',post({'course':'machine-design','node_id':'missing'})[0]==409)
        check('无对应课程时不启动应用',post({'course':'missing','node_id':'MD-C-static'})[0]==409)
        check('学习状态写入口仍关闭',post(valid,path='/api/education/learning-status')[0]==405)
        check('被拒绝的请求均未启动应用',len(opened)==count)
        report={'run_id':'EDU-MINDMAP-OBSIDIAN-OPEN-20261019-01','checks':checks,'passed':all(c['pass'] for c in checks),'app_launches_stubbed':len(opened)}
        (here/'obsidian-open-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if not report['passed']:
            raise SystemExit(1)
    finally:
        server.shutdown();server.server_close();obsidian_learning.os.startfile=original

if __name__=='__main__':
    main()
