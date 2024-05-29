准备工作，需要安装下面的组件，内网环境需要加上--trusted-host pypi.org --trusted-host files.pythonhosted.org参数
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org fastapi -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org pydantic -vvv
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org hdbcli -vvv

测试时运行下面的命令，可以在文件修改后自动重启
uvicorn main:app --reload

生产环境运行下面的命令，减少资源的占用
uvicorn main:app

监控的api endpoint 地址： http://localhost:8000/monitor
websocket endpoint: ws://localhost:8000/ws
api文档说明的地址：http://localhost:8000/redoc 和 http://localhost:8000/docs
