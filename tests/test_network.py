import io
import unittest
from unittest.mock import patch
from PIL import Image
from support import isolated_app


class QrNetworkTests(unittest.TestCase):
    def setUp(self):
        self.context = isolated_app()
        self.client, self.paths = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.client.post('/api/setup', json={'username':'admin','display_name':'管理员','password':'network-test-123'})
        self.client.post('/api/login', json={'username':'admin','password':'network-test-123'})
        self.elevator = self.client.post('/api/elevators', json={'building_name':'18栋','unit_name':'1单元','name':'2号梯'}).json()['id']
        self.path = f'/api/elevators/{self.elevator}'

    def test_saved_lan_address_is_encoded_from_loopback_and_persists(self):
        from backend import main
        base = 'http://192.168.20.9:8765'
        self.assertEqual(self.client.put('/api/network',json={'base_url':base+'/'}).status_code,200)
        with patch('backend.main.addresses', return_value=[]):
            self.assertEqual(self.client.get(self.path+'/qr-info').json()['url'],base+self.path.removeprefix('/api'))
            original = main.qrcode.make
            with patch('backend.main.qrcode.make', wraps=original) as encode:
                response=self.client.get(self.path+'/qr')
                encode.assert_called_once_with(base+self.path.removeprefix('/api'))
                Image.open(io.BytesIO(response.content)).verify()
            self.client.post('/api/logout')
            self.assertEqual(self.client.get(self.path+'/qr').status_code,401)
            self.client.post('/api/login',json={'username':'admin','password':'network-test-123'})
            self.assertEqual(self.client.get('/api/network').json()['configured_url'],base)
        self.assertTrue(any(a['target']=='局域网访问地址' for a in self.client.get('/api/audit').json()))

    def test_no_address_or_multiple_interfaces_never_yields_loopback_qr(self):
        # The test client's Host defaults to testserver, as opposed to a routable LAN IPv4 address.
        for addresses in ([], ['192.168.1.20','10.0.0.8']):
            with patch('backend.main.addresses',return_value=addresses):
                self.assertEqual(self.client.get(self.path+'/qr-info').json()['url'],'')
                self.assertEqual(self.client.get(self.path+'/qr').status_code,409)
        with patch('backend.main.addresses',return_value=['192.168.1.20']):
            result=self.client.get(self.path+'/qr-info',headers={'host':'127.0.0.1:8765'}).json()
            self.assertEqual(result['url'],f'http://192.168.1.20:8765/elevators/{self.elevator}')
        with patch('backend.main.addresses',return_value=['10.1.1.5','192.168.1.20']):
            result=self.client.get(self.path+'/qr-info',headers={'host':'192.168.1.20:8765'}).json()
            self.assertEqual(result['source'],'current')
            self.assertTrue(result['url'].startswith('http://192.168.1.20:8765/'))

    def test_invalid_urls_and_staff_cannot_change_target(self):
        for value in ['http://127.0.0.1:8765','http://localhost:8765','http://0.0.0.0:8765','http://127.1','file:///etc/passwd','javascript:alert(1)','https://example.com','http://192.168.1.2:0','http://192.168.1.2:99999','http://192.168.1.2/path','http://user@192.168.1.2','http://192.168.1.2?q=x','http://192.168.1.2#x',None,42]:
            self.assertEqual(self.client.put('/api/network',json={'base_url':value}).status_code,400,value)
        self.client.post('/api/users',json={'username':'staff','display_name':'工作人员','role':'staff','password':'network-staff-123'})
        self.client.post('/api/logout')
        self.client.post('/api/login',json={'username':'staff','password':'network-staff-123'})
        self.assertEqual(self.client.put('/api/network',json={'base_url':'http://192.168.1.2:8765'}).status_code,403)
        self.assertEqual(self.client.get('/api/network').status_code,200)

    def test_missing_or_deleted_elevator_cannot_print(self):
        self.client.put('/api/network',json={'base_url':'http://192.168.1.2:8765'})
        self.client.delete(self.path)
        self.assertEqual(self.client.get(self.path+'/qr-info').status_code,404)
        self.assertEqual(self.client.get(self.path+'/qr').status_code,404)
