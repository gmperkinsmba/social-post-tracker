import json, os, tempfile, threading, unittest, urllib.request, urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer

import sys
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
        except urllib.error.HTTPError as e:return e.code,e.read()
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

if __name__=='__main__':unittest.main()
