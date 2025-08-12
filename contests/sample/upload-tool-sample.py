import base64
from datetime import date, datetime
import os
from pathlib import Path
import tempfile
import zipfile
import requests
import json
import tomllib
import shutil
log = {
    "username": "root",
    "password": "1145141919810"
}

dom = {
    "username": "admin",
    "password": "afsV44uVd4FN3HV9"
}
yaml_template = """limits:
  memory: {}
name: {}
"""
ini_template = """short-name = {}
timelimit = {}
"""


class ComplexEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime('%Y-%m-%d')
        else:
            return json.JSONEncoder.default(self, obj)


def create_zip(source_dir, zip_path):
    """递归打包目录（不包括顶层文件夹本身）"""
    source_path = Path(source_dir).resolve()
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(source_path.parent)
                arcname = rel_path.relative_to(rel_path.parts[0])
                zipf.write(file_path, arcname)


domserver = "http://127.0.0.1:12345"
django_server = "http://127.0.0.1:8000"

user_passwd = f"{dom['username']}:{dom['password']}"
string_bytes = user_passwd.encode('utf-8')
encoded_string = base64.b64encode(string_bytes).decode('utf-8')

dom_headers = {"Authorization": f"Basic {encoded_string}"}
current_path = os.path.realpath(__file__)
directory_path = Path(os.path.dirname(current_path))
contestinfo = open(directory_path/"contest.toml", "r").read()

contestinfo_dic = tomllib.loads(contestinfo)
cname = contestinfo_dic['name']
contestinfo_json = json.dumps(contestinfo_dic, default=str)
try:
    with open(directory_path/"config.json", "w") as f:
        f.write(contestinfo_json)
    resp = requests.post(f"{domserver}/api/v4/contests", files={
        "json": ((directory_path/"config.json").name, open((directory_path/"config.json"), 'rb'))
    }, headers=dom_headers)
    print(resp.text)
except Exception as e:
    print(str(e))
    raise
resp = requests.get(f"{domserver}/api/v4/contests")
comp = resp.json()
cid = next((c["id"] for c in comp if c["name"] == cname), None)
problems_path = directory_path/"problems"
for i in problems_path.glob("*"):

    cfg = open(i/"config.toml", "r").read()
    dic = tomllib.loads(cfg)
    memlimit = dic['memlimit']
    timelimit = dic['timelimit']
    name = dic['title']
    order_char = dic['order_char']
    yaml = yaml_template.format(memlimit, name)
    ini = ini_template.format(order_char, timelimit)
    if (i/"output_validators").exists():
        yaml += "validation: custom"
    open(i/"problem.yaml", "w").write(yaml)
    open(i/"domjudge-problem.ini", "w").write(ini)
    src = Path(i/"tests")
    dst = Path(i/"data"/"secret")
    if not dst.exists():
        shutil.copytree(src, dst)
    src = Path(i/"samples")
    dst = Path(i/"data"/"sample")
    if not dst.exists():
        shutil.copytree(src, dst)
    zip_path = f"{i}_upload.zip"
    create_zip(i, zip_path)
    with open(zip_path, 'rb') as f:
        files = {'zip': (os.path.basename(zip_path), f)}
        response = requests.post(
            f"{domserver}/api/v4/contests/{cid}/problems",
            files=files,
            headers=dom_headers,
        )
    os.remove(zip_path)
    shutil.rmtree(i/"data")
    print(response)
