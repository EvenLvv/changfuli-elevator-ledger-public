"""Exercise browser script startup without requiring Playwright or a LAN NIC."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser script checks')
class BrowserDesignTest(unittest.TestCase):
    def test_health_path_uses_only_isolated_loopback_server(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200 if self.path == '/api/health' else 404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as output:
                result = subprocess.run(['node', '-e', r"""
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('tests/browser_design.cjs','utf8');
let launched=false, failure;
const stop=new Error('Reached browser launch');
const api={
  post:async(path)=>{assert.equal(path,'/api/login');return {status:()=>200}},
  get:async(path)=>{
    if(path==='/api/health'){
      const response=await fetch(process.env.AUDIT_URL+path);
      return {status:()=>response.status};
    }
    if(path==='/api/elevators')return {json:async()=>[{id:1,building_name:'18栋'}]};
    throw new Error('Unexpected request before browser launch: '+path);
  }
};
const playwright={request:{newContext:async()=>api},chromium:{launch:async()=>{launched=true;throw stop}}};
vm.runInNewContext(source,{
  require:name=>name==='playwright'?playwright:require(name), URL,
  console:{error:error=>{failure=error}},
  process:{env:process.env,exit:()=>{
    assert.ok(launched,'Health path must reach browser launch without LAN requests');
    assert.equal(failure,stop);
    console.log('Loopback health path passed');
  }}
});
"""], env={**os.environ, 'AUDIT_URL': f'http://127.0.0.1:{server.server_port}',
                           'AUDIT_OUTPUT': output, 'PLAYWRIGHT_MODULE': 'playwright'},
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('Loopback health path passed', result.stdout)
                self.assertEqual(requests, ['/api/health'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_deep_links_use_loopback_base_and_script_parses(self):
        script = Path('tests/browser_design.cjs')
        result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = script.read_text()
        self.assertIn("scan.goto(base+'/elevators/'", source)
        self.assertIn("scan.goto(base+'/elevators/999999')", source)
        self.assertNotIn('scan.goto(lan', source)
        self.assertNotIn('candidate+\'/api/health\'', source)
