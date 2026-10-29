"""Local preview with read-only content and a validated Obsidian note launcher."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import argparse
import json
import secrets
import sys

here=Path(__file__).resolve().parent
root=here.parents[4]
sys.path.insert(0,str(root/'Tools'))
from obsidian_learning import open_note

class Handler(BaseHTTPRequestHandler):
    def local_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}

    def json_response(self,status,value):
        body=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(body)

    def do_GET(self):
        if not self.local_host():
            self.send_error(403)
            return
        if urlsplit(self.path).path not in {'/','/workbench','/workbench/'}:
            self.send_error(404)
            return
        body=(here/'mindmap-prototype.html').read_bytes().replace(b'content="__MINDMAP_OPEN_TOKEN__"',b'content="'+self.server.open_token.encode('ascii')+b'"',1)
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(body)
    def do_POST(self):
        if self.path!='/api/education/open-note':
            self.send_error(405,'Read-only prototype')
            return
        origin='http://'+self.headers.get('Host','')
        token=self.headers.get('X-Mindmap-Token','')
        if not self.local_host() or self.headers.get('Origin')!=origin or not secrets.compare_digest(token.encode('utf-8'),self.server.open_token.encode('ascii')):
            self.json_response(403,{'message':'打开请求已失效，请刷新页面后重试'})
            return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2048 or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                raise ValueError()
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict) or set(data)!={'course','node_id'} or any(not isinstance(value,str) or not 0<len(value)<=128 for value in data.values()):
                raise ValueError()
        except (ValueError,UnicodeError):
            self.json_response(400,{'message':'课程或知识点参数无效'})
            return
        try:
            result=open_note(root,data['course'],data['node_id'])
        except (ValueError,KeyError):
            self.json_response(409,{'message':'对应笔记暂不可用，请检查 Obsidian 中的课程笔记'})
        except OSError:
            self.json_response(503,{'message':'本机未能启动 Obsidian，请确认应用已安装后重试'})
        else:
            self.json_response(200,result)
    def log_message(self,*args):
        pass

def create_server(port):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.open_token=secrets.token_urlsafe(32)
    return server

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8774)
    args=parser.parse_args();create_server(args.port).serve_forever()
