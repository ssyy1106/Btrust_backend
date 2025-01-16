准备工作，需要安装下面的组件，内网环境需要加上--trusted-host pypi.org --trusted-host files.pythonhosted.org参数
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org fastapi -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org pydantic -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org hdbcli -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org strawberry-graphql[fastapi] -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org psycopg2 -vvv

程序结构：
main是主程序
classes存储数据类型
html存储返回访问主页的html信息，用于在浏览器访问主页，测试websocket返回的信息是否正确
hana存储查询hana数据库的函数
config文件存储配置信息，包括hana数据库的连接信息，websocket的返回前端信息的时间间隔，各个查询时间段距离当前的天数

测试时运行下面的命令，可以在文件修改后自动重启
uvicorn main:app --reload

生产环境运行下面的命令，减少资源的占用
uvicorn main:app

监控的api endpoint 地址： http://localhost:8000/monitor
websocket endpoint: ws://localhost:8000/ws
api文档说明的地址：http://localhost:8000/redoc 和 http://localhost:8000/docs

2025-01-16 增加graphql格式的查询接口 地址：http://localhost:8000/graphql