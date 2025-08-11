# JSUT Online Judge Server

JSUT Online Judge Server 是一个用于编程题自动评测的后端服务。

## 功能特性

- 支持多种编程语言的代码评测
- 题目管理与测试用例管理
- 用户提交与评测结果反馈
- RESTful API 接口

## 部署方式

### 1. 克隆项目

```bash
git clone https://github.com/2b-creator/JSUTOnlineJudgeServer.git
cd JSUTOnlineJudgeServer
```

### 2. 创建虚拟环境并安装依赖

建议使用 Python 3.13 和 virtualenv：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd judge_server
```

### 4. 数据库迁移

```bash
python manage.py makemigrations judge
python manage.py migrate
```

### 5. 启动服务

#### 主服务

```bash
python manage.py runserver
```

#### celery
```bash
sudo apt install redis-server
cd judge_server
celery -A judge_server.celery_app worker --loglevel=info
```

服务默认运行在 `http://localhost:8000`。

## 贡献

欢迎提交 issue 和 pull request 改进本项目。

## 许可证

MIT License