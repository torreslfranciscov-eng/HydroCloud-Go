"""HTTP integration checks. Only reads Oracle; never posts station mutations.

Build first; set ConnectionStrings__HydroCloud in the environment.
Generates an ephemeral portal password, starts a local server, then stops it.
"""
import html
import json
import http.cookiejar
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

root = Path(__file__).resolve().parent.parent
project = root / "HydroCloud.Admin"
dll = project / "bin/Debug/net8.0/HydroCloud.Admin.dll"
password = secrets.token_urlsafe(32)
hashed = subprocess.check_output(["dotnet", str(dll), "--hash-password"], input=password + "\n", text=True).strip()
env = dict(os.environ, ASPNETCORE_ENVIRONMENT="Development", Admin__Username="smoke-admin", Admin__PasswordHash=hashed)
base = "http://127.0.0.1:5089"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def get(path):
    return opener.open(base + path, timeout=45)

def token(body):
    return html.unescape(re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', body).group(1))

with tempfile.TemporaryFile(mode="w+") as log:
    process = subprocess.Popen(["dotnet", str(dll), "--urls", base], cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for attempt in range(60):
            try:
                response = get("/Stations")
                break
            except (urllib.error.URLError, ConnectionError):
                if process.poll() is not None:
                    raise RuntimeError("Server exited before listening")
                time.sleep(.25)
        else:
            raise RuntimeError("Server did not start")
        assert "/Account/Login" in response.url
        login = response.read().decode()
        print("PASS: catálogo protegido por autenticación")
        try:
            opener.open(base+"/Account/Login", data=b"Username=x&Password=x")
            raise AssertionError("POST without antiforgery was accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 400
        print("PASS: POST sin antiforgery rechazado")
        data = urllib.parse.urlencode({"Username":"smoke-admin", "Password":password, "__RequestVerificationToken":token(login)}).encode()
        body = opener.open(base+"/Account/Login",data=data,timeout=45).read().decode()
        assert "Cerrar sesión" in body and "Nueva estación" in body
        ids = re.findall(r'/Stations/Edit/([a-fA-F0-9-]{36})',body)
        assert ids, "No se encontraron estaciones reales"
        print("PASS: login y catálogo real de Oracle")
        edit = get("/Stations/Edit/"+ids[0]).read().decode()
        assert 'name="Token"' in edit and 'name="Station.Basin"' in edit and "Guardar estación" in edit
        print("PASS: formulario real con catálogos y token de versión")
        create = html.unescape(get("/Stations/Create").read().decode())
        assert "Nueva estación" in create and "Guardar estación" in create
        invalid = urllib.parse.urlencode({"Station.Code":"", "Station.Name":"", "__RequestVerificationToken":token(create)}).encode()
        invalid_body = html.unescape(opener.open(base+"/Stations/Create",data=invalid,timeout=45).read().decode())
        assert "La clave es obligatoria" in invalid_body and "El nombre es obligatorio" in invalid_body
        print("PASS: validación HTTP rechaza alta vacía sin escribir")
        delete = get("/Stations/Delete/"+ids[0]).read().decode()
        assert "Confirmar baja" in delete and 'name="confirmation"' in delete
        empty = get("/Stations?search="+secrets.token_hex(16)).read().decode()
        assert "No hay estaciones" in empty
        print("PASS: alta, confirmación de baja y búsqueda vacía renderizadas sin escrituras")
        samples = json.loads(os.environ.get("EQUIPMENT_SMOKE_STATIONS", "{}"))
        for module in ["goes", "gprs", "radio", "sensores", "cotas", "componentes", "inventario"]:
            station = samples.get(module, ids[0])
            query = urllib.parse.urlencode({"stationId":station, "moduleKey":module})
            listing = html.unescape(get("/Equipment?"+query).read().decode())
            assert "Nuevo registro" in listing and "Inventario de sensores" in listing
            create = get("/Equipment/Edit?"+query).read().decode()
            assert 'name="StationId"' in create and "Guardar" in create
            invalid = urllib.parse.urlencode({"StationId":station, "ModuleKey":module, "__RequestVerificationToken":token(create)}).encode()
            invalid_body = html.unescape(opener.open(base+"/Equipment/Edit",data=invalid,timeout=45).read().decode())
            assert "validation-summary-errors" in invalid_body, module
            links = re.findall(r'href="([^"]*/Equipment/Edit/[^"?]+\?[^\"]+)"', listing)
            if samples:
                assert links, "Falta registro representativo: "+module
            if links:
                edit = html.unescape(get(links[0]).read().decode())
                assert 'name="Token"' in edit and "solo lectura" in edit
                signed = re.search(r'name="Token"[^>]*value="([^"]+)"', edit).group(1)
                record_id = re.search(r'name="Id"[^>]*value="([^"]+)"', edit).group(1)
                tampered = urllib.parse.urlencode({"StationId":"different-station", "ModuleKey":module, "Id":record_id, "Token":signed, "__RequestVerificationToken":token(edit)}).encode()
                try:
                    opener.open(base+"/Equipment/Edit",data=tampered,timeout=45)
                    raise AssertionError("Cambio de estación aceptado")
                except urllib.error.HTTPError as error:
                    assert error.code == 400
            print("PASS: módulo",module,"listado, alta inválida, edición y protección por estación")
    except Exception:
        log.seek(0)
        # Avoid dumping server logs: configuration may contain sensitive data.
        print("FAIL: revisión HTTP incompleta; comprobar configuración, red y salida de la excepción.")
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
