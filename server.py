#!/usr/bin/env python3
"""Local-first content experiment desk. Uses only the Python standard library."""
import hashlib, json, os, re, secrets, socket, threading, time
import stat
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('VCL_PORT', '8322'))
HOST = '127.0.0.1'
MAX_BODY = 32_000
def ensure_private_runtime(path):
    path = Path(path).expanduser()
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode): raise RuntimeError('Runtime directory cannot be a symbolic link.')
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid(): raise RuntimeError('Runtime directory must be owned by this user.')
    except FileNotFoundError:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid(): raise RuntimeError('Runtime directory must be owned by this user.')
        os.fchmod(fd, 0o700)
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700: raise RuntimeError('Runtime directory permissions could not be secured.')
    except Exception:
        os.close(fd)
        raise
    else: os.close(fd)

RUNTIME = Path(os.environ.get('VCL_RUNTIME_DIR', str(Path.home() / '.viral-content-lab'))).expanduser()
ensure_private_runtime(RUNTIME)
DATA_FILE = RUNTIME / 'workspace.json'
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
MAX_RESULTS = 1000

FIXTURE = {
  'audience':'People who want a small-batch cake for a neighborhood gathering',
  'source':'Fictional shop notes: three rotating cake flavors, preorder pickup on Saturdays. Synthetic scenario.',
  'hypothesis':'A specific flavor choice will prompt more saves than a general bakery introduction.',
  'stage':'Research', 'platform':'Instagram', 'post_age_hours':24,
  'hooks':['Pick the cake before you pick the playlist.','Saturday cake starts with one question: citrus or chocolate?','A neighborhood party deserves a cake with a point of view.'],
  'selected':0,
  'draft':'Saturday plans? We have three small-batch cakes on the menu, with pickup at the shop.\n\nChoose citrus, chocolate, or vanilla bean for your table.\n\nWhich one would you bring to a neighborhood gathering?',
  'claims':[],
  'review_signature':'', 'review_summary':'',
  'results':[
    {'hook':'A specific flavor choice','platform':'Instagram','age_hours':24,'cohort':'Local food posts, organic, same account','denominator':'impressions','views':500,'engagements':44,'saves':18,'conversations':4,'source_type':'synthetic','verified':False,'source':'Synthetic demo outcomes'},
    {'hook':'General bakery introduction','platform':'Instagram','age_hours':24,'cohort':'Local food posts, organic, same account','denominator':'impressions','views':500,'engagements':31,'saves':9,'conversations':2,'source_type':'synthetic','verified':False,'source':'Synthetic demo outcomes'}]
}

MAX_STATE_BYTES = 16 * 1024 * 1024
STATE_CHUNK_BYTES = 64 * 1024

class StorageSecurityError(RuntimeError):
    pass

def _runtime_fd():
    fd=None
    try:
        fd=os.open(RUNTIME,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
        info=os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid(): raise StorageSecurityError('Local workspace directory is not owned safely.')
        os.fchmod(fd,0o700)
        if stat.S_IMODE(os.fstat(fd).st_mode)!=0o700: raise StorageSecurityError('Local workspace permissions could not be secured.')
        return fd
    except Exception as exc:
        if fd is not None: os.close(fd)
        if isinstance(exc,StorageSecurityError): raise
        raise StorageSecurityError('Local workspace directory could not be opened safely.') from None

def _open_state(dirfd):
    try:
        fd=os.open(DATA_FILE.name,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),dir_fd=dirfd)
    except FileNotFoundError:
        try: os.stat(DATA_FILE.name,dir_fd=dirfd,follow_symlinks=False)
        except FileNotFoundError: return None,None
        raise StorageSecurityError('Local workspace path is not a regular file.') from None
    except OSError:
        raise StorageSecurityError('Local workspace file could not be opened safely.') from None
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1: raise StorageSecurityError('Local workspace must be an owned, unlinked regular file.')
        if stat.S_IMODE(info.st_mode)!=0o600: os.fchmod(fd,0o600)
        info=os.fstat(fd)
        if stat.S_IMODE(info.st_mode)!=0o600: raise StorageSecurityError('Local workspace file permissions could not be secured.')
        return fd,info
    except Exception as exc:
        os.close(fd)
        if isinstance(exc,StorageSecurityError): raise
        raise StorageSecurityError('Local workspace file could not be secured.') from None

def _read_existing(dirfd):
    fd, before=_open_state(dirfd)
    if fd is None: return None,None
    try:
        if before.st_size>MAX_STATE_BYTES: raise StorageSecurityError('Local workspace exceeds the 16 MiB size limit.')
        chunks=[]; total=0
        while True:
            chunk=os.read(fd,STATE_CHUNK_BYTES)
            if not chunk: break
            total+=len(chunk)
            if total>MAX_STATE_BYTES: raise StorageSecurityError('Local workspace exceeds the 16 MiB size limit.')
            chunks.append(chunk)
        after=os.fstat(fd)
        try: named=os.stat(DATA_FILE.name,dir_fd=dirfd,follow_symlinks=False)
        except OSError: raise StorageSecurityError('Local workspace changed while being read.') from None
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or (named.st_dev,named.st_ino)!=(after.st_dev,after.st_ino) or total!=after.st_size:
            raise StorageSecurityError('Local workspace changed while being read.')
        try: data=json.loads(b''.join(chunks).decode('utf-8'))
        except (UnicodeError,ValueError): raise StorageSecurityError('Local workspace is invalid; existing data was preserved.') from None
        if not isinstance(data,dict): raise StorageSecurityError('Local workspace is invalid; existing data was preserved.')
        identity=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
        return data,identity
    except StorageSecurityError:
        raise
    except OSError:
        raise StorageSecurityError('Local workspace could not be read safely.') from None
    finally: os.close(fd)

def load_data():
    dirfd=_runtime_fd()
    try:
        d,_=_read_existing(dirfd)
    finally: os.close(dirfd)
    if d is None: return json.loads(json.dumps(FIXTURE))
    for k,v in FIXTURE.items(): d.setdefault(k,json.loads(json.dumps(v)))
    return d

def save_data(d):
    encoded=json.dumps(d,ensure_ascii=False,indent=2).encode('utf-8')
    if len(encoded)>MAX_STATE_BYTES: raise StorageSecurityError('Local workspace exceeds the 16 MiB size limit.')
    dirfd=_runtime_fd(); temp_name=f'.{DATA_FILE.name}.tmp-{secrets.token_hex(12)}'; temp_identity=None; temp_created=False
    try:
        _,old_identity=_read_existing(dirfd)
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
        fd=os.open(temp_name,flags,0o600,dir_fd=dirfd)
        temp_created=True
        try:
            info=os.fstat(fd)
            temp_identity=(info.st_dev,info.st_ino)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1: raise StorageSecurityError('Temporary workspace file is not safe.')
            os.fchmod(fd,0o600)
            if stat.S_IMODE(os.fstat(fd).st_mode)!=0o600: raise StorageSecurityError('Temporary workspace permissions could not be secured.')
            view=memoryview(encoded)
            while view:
                written=os.write(fd,view[:STATE_CHUNK_BYTES])
                if written<=0: raise OSError('Temporary workspace write made no progress.')
                view=view[written:]
            os.fsync(fd)
        finally: os.close(fd)
        _,current_identity=_read_existing(dirfd)
        if current_identity!=old_identity: raise StorageSecurityError('Local workspace changed before save; existing data was preserved.')
        os.replace(temp_name,DATA_FILE.name,src_dir_fd=dirfd,dst_dir_fd=dirfd)
        temp_identity=None; temp_created=False
        os.fsync(dirfd)
        _read_existing(dirfd)
    except StorageSecurityError:
        raise
    except OSError:
        raise StorageSecurityError('Local workspace could not be saved safely.') from None
    finally:
        if temp_created:
            try:
                current=os.stat(temp_name,dir_fd=dirfd,follow_symlinks=False)
                if stat.S_ISREG(current.st_mode) and current.st_uid==os.getuid() and current.st_nlink==1 and (temp_identity is None or (current.st_dev,current.st_ino)==temp_identity): os.unlink(temp_name,dir_fd=dirfd)
            except FileNotFoundError: pass
            except OSError: pass
        os.close(dirfd)

class Handler(BaseHTTPRequestHandler):
    server_version = 'ViralLab/1.0'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send(self, code, body, content_type='application/json; charset=utf-8'):
        b = (json.dumps(body,ensure_ascii=False).encode() if isinstance(body,(dict,list)) else body.encode() if isinstance(body,str) else body)
        self.send_response(code); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(b))); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
    def authorized_origin(self):
        port = self.server.server_port
        host = self.headers.get('Host','')
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'): return False
        origin = self.headers.get('Origin')
        return origin is None or origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')
    def do_GET(self):
        if not self.authorized_origin(): return self.send(403, {'error':'Host or origin rejected'})
        p=urlparse(self.path).path
        if p == '/api/state':
            with LOCK:
                try: d=load_data()
                except StorageSecurityError: return self.send(500, {'error':'Local workspace could not be read safely.'})
                d['review_signature']=hashlib.sha256((d.get('draft','')+'\0'+d.get('source','')).encode()).hexdigest()
                return self.send(200, d)
        if p == '/api/token': return self.send(200, json.dumps({'token':TOKEN}))
        if p == '/': return self.send(200,(ROOT/'index.html').read_text(), 'text/html; charset=utf-8')
        if p == '/style.css': return self.send(200,(ROOT/'style.css').read_text(),'text/css; charset=utf-8')
        if p == '/app.js': return self.send(200,(ROOT/'app.js').read_text(),'text/javascript; charset=utf-8')
        return self.send(404, {'error':'Not found'})
    def do_POST(self):
        if not self.authorized_origin(): return self.send(403, {'error':'Host or origin rejected'})
        if self.headers.get('X-Request-Token') != TOKEN: return self.send(403, {'error':'Request token rejected'})
        try: n=int(self.headers.get('Content-Length','0'))
        except ValueError: return self.send(400, {'error':'Invalid content length'})
        if n < 1 or n > MAX_BODY: return self.send(413, {'error':'Payload must be 1 to 32000 bytes'})
        try: data=json.loads(self.rfile.read(n))
        except (ValueError, OSError): return self.send(400, {'error':'Invalid JSON'})
        if not isinstance(data,dict): return self.send(400, {'error':'JSON object required'})
        with LOCK:
            try: old=load_data()
            except StorageSecurityError: return self.send(500, {'error':'Local workspace could not be read safely.'})
            if self.path == '/api/state':
                for field, limit in [('audience',1200),('source',3000),('hypothesis',1200),('draft',6000)]:
                    if not isinstance(data.get(field),str) or len(data[field])>limit: return self.send(400, {'error':f'Invalid {field}'})
                changed=old['draft'] != data['draft'] or old['source'] != data['source']
                old.update({k:data[k] for k in ('audience','source','hypothesis','draft')})
                old['stage'] = data.get('stage') if data.get('stage') in ('Research','Draft','Review','Measured') else 'Research'
                old['selected'] = int(data.get('selected',0)) if str(data.get('selected','0')).isdigit() else 0
                if not 0 <= old['selected'] < len(old['hooks']): old['selected']=0
                if changed:
                    old['claims']=[]; old['review_signature']=''; old['review_summary']=''
                elif data.get('review_signature') == hashlib.sha256((old['draft']+'\0'+old['source']).encode()).hexdigest():
                    old['claims'] = data.get('claims',[]) if isinstance(data.get('claims',[]),list) else []
                    if len(old['claims'])>30 or any(not isinstance(c,dict) or not isinstance(c.get('text'),str) or len(c['text'])>1200 or not isinstance(c.get('source',''),str) or len(c.get('source',''))>1200 for c in old['claims']): return self.send(400, {'error':'Invalid claim review data'})
                    old['review_signature']=data['review_signature']
                    old['review_summary']=data.get('review_summary','')[:500]
                else:
                    old['claims']=[];old['review_signature']='';old['review_summary']=''
                try: save_data(old)
                except StorageSecurityError: return self.send(500, {'error':'Local workspace could not be saved safely.'})
                return self.send(200, json.dumps(old))
            if self.path == '/api/result':
                keys=('hook','platform','age_hours','cohort','denominator','views','engagements','saves','conversations','source','source_type')
                if any(k not in data for k in keys): return self.send(400, {'error':'Outcome fields are required'})
                try:
                    row={k:data[k] for k in keys}; row.update({'age_hours':int(row['age_hours']),'views':int(row['views']),'engagements':int(row['engagements']),'saves':int(row['saves']),'conversations':int(row['conversations']),'verified':row['source_type']=='verified'})
                except (ValueError,TypeError): return self.send(400, {'error':'Age and outcome counts must be whole numbers'})
                if any(v<0 for k,v in row.items() if k in ('age_hours','views','engagements','saves','conversations')) or row['views']==0 or max(map(len,map(str,row.values())))>1500: return self.send(400, {'error':'Invalid outcome values'})
                if row['source_type'] not in ('synthetic','manual','verified'): return self.send(400, {'error':'Choose a valid result source type'})
                if len(old['results']) >= MAX_RESULTS: return self.send(409, {'error':'Result history is full (1,000 rows). Export your records or reset the workspace before adding more.'})
                old['results'].append(row); old['stage']='Measured'
                try: save_data(old)
                except StorageSecurityError: return self.send(500, {'error':'Local workspace could not be saved safely.'})
                return self.send(200,json.dumps(old))
            if self.path == '/api/reset':
                try: save_data(json.loads(json.dumps(FIXTURE)))
                except StorageSecurityError: return self.send(500, {'error':'Local workspace could not be reset safely.'})
                return self.send(200,load_data())
        return self.send(404, {'error':'Not found'})
    def log_message(self, fmt,*args): pass

class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = HOST
        self.server_port = self.socket.getsockname()[1]

def make_server(host=HOST, port=PORT):
    if host != HOST:
        raise ValueError('The local server must bind to loopback')
    return LocalHTTPServer((HOST, port), Handler)

if __name__ == '__main__':
    server=make_server()
    print(f'Social Post Tracker listening at http://{HOST}:{server.server_port}')
    server.serve_forever()
