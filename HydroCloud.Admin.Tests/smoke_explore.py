"""Read-only Oracle integration; writes only aggregate metrics in a temporary directory."""
import datetime as dt
import html
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

project=Path(__file__).resolve().parent.parent/'HydroCloud.Admin'
dll=project/'bin/Debug/net8.0/HydroCloud.Admin.dll'
base='http://127.0.0.1:5091'
def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
public,reader,admin=client(),client(),client()
password=secrets.token_urlsafe(24)
hashed=subprocess.check_output(['dotnet',str(dll),'--hash-password'],input=password+'\n',text=True).strip()
def get(c,path):return c.open(base+path,timeout=45)
def login(c,user):
    body=get(c,'/Account/Login').read().decode()
    token=html.unescape(re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',body).group(1))
    return c.open(base+'/Account/Login',urllib.parse.urlencode({'Username':user,'Password':password,'__RequestVerificationToken':token}).encode(),timeout=45)
def denied(c,path,status):
    try:get(c,path);raise AssertionError('Unexpected success: '+path)
    except urllib.error.HTTPError as error:assert error.code==status,(error.code,path)

with tempfile.TemporaryDirectory(prefix='hydrocloud-query-smoke-') as directory, tempfile.TemporaryFile() as log:
    env=dict(os.environ,ASPNETCORE_ENVIRONMENT='Development',Admin__Username='test-admin',Admin__PasswordHash=hashed,Consultation__Username='test-reader',Consultation__PasswordHash=hashed,Analytics__Path=directory+'/visitors.json')
    p=subprocess.Popen(['dotnet',str(dll),'--urls',base],cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:home=get(public,'/');break
            except urllib.error.URLError:time.sleep(.25)
        else:raise AssertionError('Server unavailable')
        assert 'últimos 7 días' in html.unescape(home.read().decode())
        assert '/Account/Login' in get(public,'/Stations').url
        assert '/Account/Login' in get(public,'/Explore/Visitors').url
        stations=json.load(get(public,'/Explore/Stations'));assert stations
        signals=json.load(get(public,'/Explore/Availability'))
        assert {s['stationId'] for s in signals['stations']}=={s['id'] for s in stations}
        assert all(set(s)=={'stationId','state'} and s['state'] in ['recent','week','historical','empty','unknown'] for s in signals['stations'])
        assert json.load(get(public,'/Explore/Availability'))==signals
        print('PASS: semáforo completo con caché y sin exponer valores o fechas históricas',flush=True)
        station=next((s for s in stations if s['code']=='COROTAM043'),stations[0])
        now=dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)
        query={'stationId':station['id'],'start':(now-dt.timedelta(days=6)).isoformat(),'end':now.isoformat()}
        for product in ['variables','horario','diario','transmisiones','recepcion','eficiencia','lluvia','eventos','alertas']:
            query['product']=product
            response=get(public,'/Explore/Data?'+urllib.parse.urlencode(query));data=json.load(response)
            assert len(data['rows'])<=2000 and data['product']==product
            print('PASS: consulta real',product,len(data['rows']),'filas',flush=True)
        old=dict(query,product='variables',start=(now-dt.timedelta(days=30)).isoformat(),end=(now-dt.timedelta(days=29)).isoformat())
        for route in ['Data','Export']:denied(public,'/Explore/'+route+'?'+urllib.parse.urlencode(old),400)
        print('PASS: API y CSV públicos bloquean periodos anteriores a siete días',flush=True)
        login(reader,'test-reader')
        assert json.load(get(reader,'/Explore/Data?'+urllib.parse.urlencode(old)))['product']=='variables'
        for path in ['/Stations','/Explore/Visitors','/Equipment']:
            denied(reader,path,403)
        print('PASS: lector consulta histórico pero no tiene administración',flush=True)
        login(admin,'test-admin');assert 'Visitas y uso' in html.unescape(get(admin,'/Explore/Visitors').read().decode())
        query['product']='variables';csv=get(public,'/Explore/Export?'+urllib.parse.urlencode(query));assert 'text/csv' in csv.headers['Content-Type']
        counts=json.loads(Path(directory+'/visitors.json').read_text());assert sum(x['PublicVisits'] for x in counts)>0 and sum(x['Queries'] for x in counts)>=9
        print('PASS: estadísticas privadas persistentes y exportación pública limitada',flush=True)
    finally:
        p.terminate()
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:p.kill();p.wait()
