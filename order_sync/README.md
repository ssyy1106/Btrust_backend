# Odoo → SAP 基础订单同步

代码与 FastAPI 放在同一项目，Worker 和 Beat 单独运行。FastAPI 无需增加 startup 定时器。只配置两个定时任务，没有 recovery、过期租约回收或宕机任务补投。

## 配置

统一从项目根目录 `config.ini` 读取，路径不依赖启动目录：

- `[postgresqlstorestock]`：复用现有 storestock 库及 public.order_sync / public.order_outbox，不建表、不修改结构。
- `[odoo_order_sync]`：复用 Testing/test_odoo.py 已调通的连接。
- `[sap_order_sync]`：复用 Testing/test_sap.py 的 **测试库**连接。
- `[celery_order_sync]`：RabbitMQ 地址、独立队列 order_sync、时区、间隔和批量大小。RabbitMQ 暂填本地 guest 默认连接；若已建立专用用户或 vhost，修改 broker_url。

上线前配置以下真实映射；代码不会猜测客户或商品编码：

```ini
[sap_order_sync]
; product.product 上保存 SAP ItemCode 的实际字段名
odoo_product_itemcode_field =
; SAP Orders standard field storing the synchronization external key (e.g. ODOO-BT-107)
external_key_field = NumAtCard
; 可选：stock.warehouse 上的 SAP 仓库编码字段
odoo_warehouse_code_field =
; 可选：未配置仓库字段时使用固定 SAP 仓库编码
warehouse_code =

[sap_customer_mapping]
; res.partner.commercial_partner_id = SAP CardCode
7 = C100001
8 = C100002
9 = C100035
10 = C100003
```

客户映射依次为 Mississauga、North York、Montreal、Terra。程序从订单 `partner_id` 读取 `res.partner.commercial_partner_id`，使用该商业实体 ID 查 `[sap_customer_mapping]`，子联系人使用所属公司的 CardCode；不使用订单内部 `company_id` 或销售员。新增门店只需增加 `ID = CardCode` 并重启 Worker。缺少商业实体或映射为空、未配置时，订单进入 review，不创建 SAP 订单。不再需要 `odoo_partner_cardcode_field` 或 Odoo 客户自定义字段。

商品行使用 Odoo 数量、UnitPrice、DiscountPercent。当前基础实现要求商品计量单位、币种、税务及客户商业规则在两端匹配；如两端不同，需要补充对应映射。缺少配置、字段或编码时记录 review，不创建 SAP 订单。外部键的查询检查不等于 SAP 服务端唯一约束。

Odoo 扫描 `account.move` 中 `move_type = out_invoice`、`state in (draft, posted)` 且 `write_date` 在配置时区（默认 America/Toronto）当天范围内的客户发票，按发票 ID 分页。时间范围转换为 UTC，不再按销售订单的时间筛选。通过 `invoice_line_ids → account.move.line.sale_line_ids → sale.order.line.order_id` 找到关联的销售订单，仅将 `state = sale` 的订单入库；没有销售订单关联的发票跳过。一张发票可关联多个订单，多张发票关联同一订单时去重。重复读取不新增事件、不更新已入库订单；因此本版同步首次创建，不同步后续订单修改。数据库按之前的两张表只保存订单引用，Worker 从 Odoo 重新读取完整订单，不保存快照。

每次轮询重新扫描当天更新的发票，没有持久化增量游标或跨天补偿。若发票在前一天更新、订单直到次日才满足条件且发票没有再次更新，或服务停机跨过当天，需另行补扫。

配置更新后重启 Worker 和 Beat。密码中的 `%` 按项目现有约定写成 `%%`。

## 启动

在项目根目录打开两个终端：

```powershell
python -m celery -A celery_app:celery_app worker --loglevel=INFO --pool=solo
python -m celery -A celery_app:celery_app beat --loglevel=INFO
```

本机 Windows 使用 solo 池；生产部署建议使用 Linux Worker。同一环境只运行一个 Beat。不要把这些命令指向 worker/app/celery_app.py，那是已有的其他业务 Worker。新流程使用独立 order_sync 队列。

默认每 60 秒读取 Odoo，每 10 秒发布 Outbox。任务无需结果 backend，结果以 PostgreSQL 状态为准。

## 状态和重试

首次入库在同一事务插入 pending 订单和 pending Outbox；已存在的订单直接跳过。Publisher 用 SKIP LOCKED 认领一条事件，提交后向持久化队列发布持久化消息，收到 RabbitMQ confirm 后记录 published。publish_attempts 统计发布尝试次数，失败间隔逐步增长至 300 秒。Worker 不要求 Outbox 已是 published，避免消费快于发布状态回写的竞争。

Worker 原子认领 pending 或到期 retry，增加 attempt_count，通过 SAP NumAtCard 先查询相同外部键。已存在则回写 SAP 单号并置 done；没有才读取 Odoo 明细并创建。

创建请求之前的临时错误可重试，默认最多 **5 次总尝试**。Publisher 的第二个定时任务同时生成到期业务重试事件。配置/数据错误、超过上限和任何创建请求后的异常进入 review，last_error 保存原因。重复消息遇到 done、review 或已被认领的 processing 会跳过。

本版不扫描/重置 publishing 或 processing。进程在认领后宕机、发布成功但数据库回写失败、SAP 成功但 done 回写失败，都可能留下这些状态，需人工核实。网络不确定的 review 也需人工检查 SAP，不能直接盲目重发。lock_token 用来保护状态回写，locked_until 字段暂不启用。

## 验证

```powershell
python -m pytest Testing/o_test_order_sync.py -q
```

这些测试模拟外部系统，不调用 SAP 创建订单。原来的 Testing/test_sap.py 和 Testing/test_odoo.py 也已改为从同一 config.ini 读取连接配置。
