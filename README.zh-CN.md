<p align="center">
  <img src="docs/assets/hero.svg" alt="PriceWitness — 本地小票价格证据" width="100%">
</p>

# PriceWitness

**把杂货小票文本转换成可审计的单位价格历史；完全本地、确定性运行、不依赖云端 AI。**

[在线演示](https://kanadek.github.io/pricewitness/) · [English](README.md) · [调研与排重](docs/RESEARCH.md) · [故障修复](docs/TROUBLESHOOTING.md)

## 它解决的不是 OCR，而是 OCR 之后最难的一层

OCR 可以得到文本，库存软件知道冰箱里有什么，记账软件知道总金额；但 `DK COFFEE 450 G`、`DARK COFFEE 500G` 是否是同一个商品、包装是否缩水、每 100 克到底涨了多少，往往仍要手工判断。

PriceWitness 专门解决这层“可审阅的身份与单位价格证据”：

- 对原始 UTF-8 小票建立 SHA-256 证据记录并防重复导入；
- 用小型 JSON 别名表映射门店缩写，冲突时拒绝猜测；
- 统一 kg/g/lb/oz/L/ml/fl oz/件数；
- 检测单位价格上涨与包装缩水；
- 保留未识别条目，生成明确的 review queue；
- 输出离线 HTML、确定性 JSON 和防表格公式注入 CSV；
- 校验 SQLite、外键、计算结果和可选的原始文件哈希。

它不是另一个收据收纳箱、家庭 ERP、OCR 服务或超市爬虫。边界与竞品对比见 [调研快照](docs/RESEARCH.md)。

## 一条命令看见完整功能

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\pricewitness demo --output .demo
```

打开 `.demo/report.html`。这个报告不请求网络。v0.1.0 示例应得到：3 张小票、16 个条目、15 个已映射、1 个待审阅、5 个价格/包装信号、个人篮子变化 `+14.87%`。

## 导入你自己的小票

先用任意本地 OCR、扫描软件或电子小票导出得到 UTF-8 文本，再执行：

```powershell
pricewitness init groceries.db
pricewitness ingest groceries.db receipts\receipt-1.txt receipts\receipt-2.txt `
  --aliases aliases.json --currency USD
pricewitness analyze groceries.db --output analysis.json
pricewitness report groceries.db --output price-report.html
pricewitness export groceries.db --output observations.csv
pricewitness verify groceries.db receipts\receipt-1.txt receipts\receipt-2.txt
```

别名规则可以原子追加并重新匹配历史条目：

```powershell
pricewitness aliases add aliases.json `
  --product-key local-jam `
  --product-name "Local jam" `
  --category pantry `
  --pattern "LOCAL JAM 250G" `
  --package "250 g"
pricewitness aliases validate aliases.json
pricewitness rematch groceries.db --aliases aliases.json
```

`rematch` 只更新派生身份字段，不改原始哈希、原文行、日期或金额。

## 结果应该怎样理解

- “涨价”只比较同一已映射商品的相邻单位价格，默认阈值 10%。
- “缩水”要求基础数量至少下降 5%，同时总价不低于上次的 95%。
- “篮子变化”是基于你提供的小票，不是 CPI 或市场结论。
- “最佳门店”只是各门店最近一次已观察价格，不是实时货架报价。
- 单位冲突会阻止比较并要求人工复核。

## 隐私与安全

无遥测、无账号、无 CDN、无外部字体、无 API 请求。数据库只保存来源文件名，不保存绝对路径；HTML 对所有小票字段转义且不嵌入整张小票原文；CSV 会中和 `= + - @` 开头的单元格。

小票仍可能包含姓名、地址、会员号、卡号后四位和消费习惯，请把数据库与原件视为私密数据。公开问题前先读 [SECURITY.md](SECURITY.md)。

## 验收命令

```powershell
python -m pip install -e ".[dev]"
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
python scripts\release_check.py
```

测试门禁要求分支覆盖率至少 90%。发布检查还会隔时构建两套 wheel/sdist/demo ZIP 并逐字节比较全部资产，执行 Twine 元数据与校验和检查，在全新虚拟环境安装 wheel、运行打包后的 demo、核验原始 SHA-256，并扫描高风险密钥模式。

## 失败时如何修

- `verify` 返回 1：完整性或哈希失败；保留原件，不要先覆盖或删除。
- 返回 2：输入、别名结构、路径权限或 SQLite 错误。
- `review` 不是失败：添加窄范围别名，验证后再 `rematch`。
- 小计警告可能来自优惠券、押金或税费舍入；它会保留供人工核对。

完整诊断顺序与修复命令见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 许可

MIT。示例门店与商品均为虚构数据。
