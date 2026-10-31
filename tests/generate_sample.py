"""Generate a real API export with mixed photos, fault times and an empty elevator."""
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from docx import Document
from support import isolated_app

output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'docs' / 'qa'
output.mkdir(parents=True, exist_ok=True)
# These same small files are used by the browser upload/retry regression.
for fmt, filename in [('PNG', '现场.png'), ('WEBP', '现场.webp')]:
    Image.new('RGB', (800, 500), 'steelblue').save(output / filename, format=fmt)
Document().save(output / '报价.docx')
from backend.archive_excel import workbook_bytes
(output / '档案.xlsx').write_bytes(workbook_bytes([{'building_name':'批量导入测试栋','unit_name':'1单元','name':'1号梯','equipment_number':'000123','maintenance_phone':'00123456'}]))
with isolated_app() as (client, paths):
    def post(path, data):
        response = client.post(path, json=data)
        assert response.status_code == 200, response.text
        return response.json()
    credentials = {'username':'qa','display_name':'验收管理员','password':'qa-sample-password'}
    post('/api/setup', credentials); post('/api/login', credentials)
    building = post('/api/buildings', {'name':'18栋'})['id']
    unit = post('/api/units', {'building_id':building,'name':'1单元'})['id']
    elevator = post('/api/elevators', {'unit_id':unit,'name':'1号梯','brand':'演示品牌','model':'示例型号','equipment_number':'QA-001'})['id']
    for n, kind in enumerate(('日常维保','故障','维修','配件更换')):
        day = f'2026-09-{18+n}'
        data = {'elevator_id':elevator,'type':kind,'title':['半月维保检查','3层厅门无法关闭','更换门锁开关后试运行','门锁开关质保登记'][n],
                'occurred_on':day,'work_content':'检查厅门与轿门运行情况，核对门锁触点。\n完成现场照片和处理情况归档。',
                'workers':'张师傅、物业工作人员','company':'演示维保有限公司','resolution':'按现场检查结果完成处理并登记。','cost_yuan':'260','completed':True}
        if kind == '故障':
            data.update(symptom='3层厅门无法关闭',reported_at=day+'T09:12',arrived_at=day+'T09:30',restored_at=day+'T10:36',recovered=True,stopped=True)
        if kind in ('维修','配件更换'):
            data['parts'] = [{'name':'门锁开关','model':'MS-01','quantity':1,'unit_price_yuan':'260','warranty_days':365,
                              'replaced_on':day,'reason':'触点损坏','brand':'演示品牌','notes':'核验安装位置'}]
        event = post('/api/events', data)['id']
        if kind == '维修':
            for index, (fmt, size) in enumerate((('PNG',(1000,600)),('WEBP',(600,1000)),('JPEG',(1000,600)),('JPEG',(600,1000)),('PNG',(800,800)))):
                photo = Image.new('RGB', size, ['steelblue','darkgreen','darkred','orange','slategray'][index])
                ImageDraw.Draw(photo).text((30,30), f'PHOTO {index+1} / 2026-09-20 / ORIGINAL WATERMARK', fill='white')
                raw = io.BytesIO(); photo.save(raw, format=fmt)
                filename = 'cgi-bin_mmwebwx-bin_webwxgetmsgimg__&MsgID=7773237&skey=@crypt_227815e3.png' if index==0 else f'现场{index+1}.{fmt.lower()}'
                result = client.post(f'/api/events/{event}/attachments',files={'file':(filename,raw.getvalue(),'image/'+fmt.lower())},data={'category':'工作现场照片'})
                assert result.status_code == 200, result.text
            raw = io.BytesIO(); Document().save(raw)
            result = client.post(f'/api/events/{event}/attachments',files={'file':('维修报价单.docx',raw.getvalue(),'application/octet-stream')},data={'category':'报价单'})
            assert result.status_code == 200, result.text
    post('/api/elevators', {'unit_id':unit,'name':'2号梯','brand':'演示品牌'})
    result = client.get('/api/export',params={'scope':'building','building_id':building,'start':'2026-09-01','end':'2026-09-30'})
    assert result.status_code == 200, result.text
    target = output / 'audit-sample.docx'
    target.write_bytes(result.content)
    print(target)
