import sqlite3
# 在硬盘上创建数据库
conn = sqlite3.connect('db.sqlite3')
cur = conn.cursor()
cur.execute("""SELECT name
FROM sqlite_master
WHERE type = 'table';""")
print(cur.fetchall())