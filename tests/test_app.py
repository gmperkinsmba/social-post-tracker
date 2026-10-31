import json, os, tempfile, threading, unittest, urllib.request, urllib.error, subprocess, sys
from pathlib import Path
from http.server import ThreadingHTTPServer

import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); server.RUNTIME=Path(cls.temp.name); os.chmod(server.RUNTIME,0o700); server.DATA_FILE=server.RUNTIME/'workspace.json'; server.PORT=0
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler); cls.port=cls.http.server_address[1]
        server.PORT=cls.port; cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.base=f'http://127.0.0.1:{cls.port}'
        cls.token=json.loads(urllib.request.urlopen(cls.base+'/api/token').read())['token']
    @classmethod
    def tearDownClass(cls): cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()
    def request(self,path,body=None,headers=None):
        h=headers or {}
        if body is not None: h={**h,'Content-Type':'application/json','X-Request-Token':server.TOKEN}; data=json.dumps(body).encode()
        else: data=None
        req=urllib.request.Request(self.base+path,data=data,headers=h)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:
            with e:return e.code,e.read()
    def test_bootstrap_and_template_state(self):
        status,b=self.request('/api/state');self.assertEqual(status,200);self.assertEqual(len(json.loads(b)['hooks']),3)
    def test_host_origin_token_and_size_guards(self):
        self.assertEqual(self.request('/api/state',{'audience':''},{'Host':'evil.test'})[0],403)
        self.assertEqual(self.request('/api/state',{'audience':''},{'Origin':'https://evil.test'})[0],403)
        req=urllib.request.Request(self.base+'/api/state',data=b'{}',headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,403)
        req=urllib.request.Request(self.base+'/api/state',data=b'x'*32001,headers={'X-Request-Token':server.TOKEN})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
        self.assertEqual(e.exception.code,413)
    def test_state_roundtrip_and_draft_change_invalidates_review(self):
        st=json.loads(self.request('/api/state')[1]);sig=st['review_signature'];st.update({'claims':[{'text':'a factual sentence','verified':True,'kind':'source','source':'Fixture'}], 'review_signature':sig,'review_summary':'Readable'})
        self.assertEqual(self.request('/api/state',st)[0],200)
        st=json.loads(self.request('/api/state')[1]);self.assertTrue(st['claims'])
        st['draft']+=' Changed.'; self.assertEqual(self.request('/api/state',st)[0],200)
        st=json.loads(self.request('/api/state')[1]);self.assertEqual(st['claims'],[]);self.assertEqual(st['review_summary'],'')
    def test_source_change_invalidates_review_and_reset_restores_fixture(self):
        st=json.loads(self.request('/api/state')[1]);st['claims']=[{'text':'claim','verified':True,'source':'source'}];st['review_signature']=st['review_signature'];self.request('/api/state',st)
        st=json.loads(self.request('/api/state')[1]);st['source']+=' changed';self.request('/api/state',st);st=json.loads(self.request('/api/state')[1]);self.assertEqual(st['claims'],[])
        status,b=self.request('/api/reset',{});self.assertEqual(status,200);fresh=json.loads(b);self.assertEqual(len(fresh['results']),2);self.assertEqual(len(fresh['hooks']),3)
    def test_bad_claims_and_result_validation(self):
        st=json.loads(self.request('/api/state')[1]);st['claims']=[{'text':'x'*1201}]
        self.assertEqual(self.request('/api/state',st)[0],400)
        bad={'hook':'x','platform':'Instagram','age_hours':'24','cohort':'x','denominator':'views','views':'0','engagements':'1','saves':'0','conversations':'0','source':'x','source_type':'manual'}
        self.assertEqual(self.request('/api/result',bad)[0],400)
    def test_result_attach_displays_explicit_synthetic_provenance_and_match_fields(self):
        row={'hook':'Synthetic check','platform':'Instagram','age_hours':'24','cohort':'same cohort','denominator':'impressions','views':'100','engagements':'10','saves':'2','conversations':'1','source':'test fixture','source_type':'synthetic'}
        self.assertEqual(self.request('/api/result',row)[0],200);st=json.loads(self.request('/api/state')[1]);self.assertEqual(st['results'][-1]['source_type'],'synthetic');self.assertFalse(st['results'][-1]['verified'])

    def test_result_history_cap_accepts_last_row_then_rejects_without_dropping(self):
        self.request('/api/reset',{})
        state=server.load_data()
        while len(state['results']) < server.MAX_RESULTS-1:
            state['results'].append(dict(state['results'][0]))
        server.save_data(state)
        row={'hook':'Cap check','platform':'Instagram','age_hours':24,'cohort':'fixture','denominator':'impressions','views':100,'engagements':10,'saves':2,'conversations':1,'source':'synthetic test','source_type':'synthetic'}
        self.assertEqual(self.request('/api/result',row)[0],200)
        full=json.loads(self.request('/api/state')[1]);self.assertEqual(len(full['results']),server.MAX_RESULTS)
        status,body=self.request('/api/result',row);self.assertEqual(status,409);self.assertIn('history is full',body.decode())
        self.assertEqual(len(json.loads(self.request('/api/state')[1])['results']),server.MAX_RESULTS)

    def test_symlink_runtime_is_rejected_without_changing_target_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target';target.mkdir(mode=0o755);os.chmod(target,0o755)
            link=Path(tmp)/'runtime';link.symlink_to(target, target_is_directory=True)
            env={**os.environ,'VCL_RUNTIME_DIR':str(link)}
            run=subprocess.run([sys.executable,'-c','import server'],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertIn('symbolic link',run.stderr)
            self.assertEqual(target.stat().st_mode & 0o777,0o755)
            with patch('server.os.getuid',return_value=target.stat().st_uid+1):
                with self.assertRaisesRegex(RuntimeError,'owned by this user'):server.ensure_private_runtime(target)
            self.assertEqual(target.stat().st_mode & 0o777,0o755)

    def test_workspace_symlink_read_and_save_fail_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'outside.json';target.write_text('{"keep":true}');os.chmod(target,0o644)
            server.DATA_FILE.unlink(missing_ok=True);server.DATA_FILE.symlink_to(target)
            try:
                with self.assertRaises(server.StorageSecurityError):server.load_data()
                with self.assertRaises(server.StorageSecurityError):server.save_data(server.FIXTURE)
                self.assertEqual(target.read_text(),'{"keep":true}');self.assertEqual(target.stat().st_mode & 0o777,0o644)
                self.assertEqual(self.request('/api/state')[0],500)
            finally:server.DATA_FILE.unlink(missing_ok=True)

    def test_legacy_temp_symlink_is_not_followed_or_chmodded(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'outside.tmp';target.write_text('keep');os.chmod(target,0o644)
            legacy=server.DATA_FILE.with_suffix('.tmp');legacy.unlink(missing_ok=True);legacy.symlink_to(target)
            try:
                server.save_data(server.FIXTURE)
                self.assertEqual(target.read_text(),'keep');self.assertEqual(target.stat().st_mode & 0o777,0o644)
                self.assertTrue(legacy.is_symlink())
            finally:legacy.unlink(missing_ok=True);server.DATA_FILE.unlink(missing_ok=True)

    def test_failed_atomic_save_keeps_old_state_and_cleans_unique_temp(self):
        state=server.load_data();server.save_data(state);before=server.DATA_FILE.read_bytes()
        with patch('server.os.write',side_effect=OSError('synthetic write failure')):
            with self.assertRaises(server.StorageSecurityError):server.save_data({**state,'draft':'changed'})
        self.assertEqual(server.DATA_FILE.read_bytes(),before)
        self.assertEqual(list(server.RUNTIME.glob(f'.{server.DATA_FILE.name}.tmp-*')),[])

    def test_corrupt_workspace_is_preserved_and_never_replaced_with_fixture(self):
        raw=b'{not valid json'
        server.DATA_FILE.write_bytes(raw);os.chmod(server.DATA_FILE,0o600)
        with self.assertRaises(server.StorageSecurityError):server.load_data()
        with self.assertRaises(server.StorageSecurityError):server.save_data(server.FIXTURE)
        self.assertEqual(self.request('/api/reset',{})[0],500)
        self.assertEqual(server.DATA_FILE.read_bytes(),raw)
        server.DATA_FILE.unlink(missing_ok=True)

    def test_hardlinked_workspace_and_oversized_workspace_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'outside.json';target.write_text('{}');os.chmod(target,0o644)
            server.DATA_FILE.unlink(missing_ok=True);os.link(target,server.DATA_FILE)
            try:
                with self.assertRaises(server.StorageSecurityError):server.load_data()
                self.assertEqual(target.read_text(),'{}');self.assertEqual(target.stat().st_mode & 0o777,0o644)
            finally:server.DATA_FILE.unlink(missing_ok=True)
        server.DATA_FILE.write_bytes(b' '*(server.MAX_STATE_BYTES+1));os.chmod(server.DATA_FILE,0o600)
        with self.assertRaises(server.StorageSecurityError):server.load_data()
        server.DATA_FILE.unlink(missing_ok=True)
if __name__=='__main__':unittest.main()
