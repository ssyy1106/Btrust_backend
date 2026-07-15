当前配置下的主要地址是：

HTTP:
http://app.midlandfood.ca:8000
http://10.16.10.66:8000

HTTPS:
https://app.midlandfood.ca:8443
https://10.16.10.66:8443

FastAPI Swagger:
https://app.midlandfood.ca:8443/docs

首次启动：

docker compose up -d --build

启动后可以使用postman测试一下网址(需要增加header   {key: x-api-key  Value: 2yK8Qm9wJfT6cNxP4aLzV7HsRe3UbD5kMgY1qWpCv8XnFtEhZ})：
http://app.midlandfood.ca:8000/netsuite/lot?limit=50&offset=0

配置说明：
.env文件里面以下变量用于配置netsuite账号
NETSUITE_ACCOUNT_ID
NETSUITE_CLIENT_ID
NETSUITE_CERTIFICATE_ID
NETSUITE_PRIVATE_KEY_FILE
.env文件里面以下变量用于配置前端或者app的key
API_KEYS
