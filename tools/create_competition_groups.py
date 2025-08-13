import requests
gp = {
    'group': 'div.4',
    'basic_rate': 0
}
login = {
    "username": "root",
    "password": "rootpwd"
}
server = "http://127.0.0.1:8000"
response = requests.post(f"{server}/api/login/", json=login)
login_info = response.json()

headers = {
    "Authorization": f"Bearer {login_info['access']}"
}

response = requests.post(
    f"{server}/api/add_contest_rate_group/", json=gp, headers=headers)
print(response)
