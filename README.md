# 接入服务应答的承诺提取与验收安排

园区接入服务合同演练材料。这里的需求和技术承诺均为合成文本。

## 资料

`materials/` 保存本地合成资料，每行是一个 UTF-8 JSON 对象。业务记录编号只在所在文件中唯一。各来源文书保持原有措辞，便于按原文定位。

相同条款号代表同一轮需求的相关要求，实际更正文义以公开补遗为准。附件可能有不同统计口径，资料中的条件表的范围与试验参数用于采购会上讨论的同一次工况。

### terms.jsonl

字段为 `id`、`type`、`issued`、`parent`、`text`。需求书、答疑与补遗。parent 指明更正的文件系列，具体改变按正文约束。未更正的同号条款继续有效。

### replies.jsonl

字段为 `id`、`supplier`、`part`、`issued`、`heading`、`prose`。应答、条件页与澄清沿用供应商名称，每份材料仍有自己的行文状态。标题不是结构化承诺。

### conditions.jsonl

字段为 `id`、`facility`、`scope`、`interval`、`detail`。项目实办边界。记录哪些范围纳入验收，以及同一工况下能否选用共用试验。

### minutes.jsonl

字段为 `id`、`time`、`state`、`vendor`、`basis`、`notes`。采购会议已形成的验收意见，可查看当时采用材料及本来承诺，不代表新材料下一定继续适用。

## 资料核对

运行环境使用 Python 3.11.2 和标准库。进入项目目录运行以下命令，读取全部交接文件并核对字段、记录编号和资料引用。

```sh
python3 -m unittest discover -s tests -v
```

## 比对工具

`acceptance/` 是只依赖标准库的比对项目，把需求书、补遗、正文答复和服务条件重新整理为可以拿去安排验收的条款覆盖意见：

- 从需求文本识别指标、单位、统计口径、比较符号、对象与适用范围；补遗与答疑按更正链落到条款上，未更正的同号条款继续有效，每次更正留沿革。
- 从供应商材料分出宣传、意向与可验收承诺；需采购方另选的项目未经确认不当作合同默认；附件沿用的工况与限定（负载上限、测区、窗口、启用条件）随证据一起带出。
- 同一句需求拆出的每个场景（平时/满载、东区/西区）各自核对，一个场景的高指标不盖另一个场景的缺项；正文与附件组合才满足时，核对需求书是否允许跨接入方式组合以及切换前后的条件。
- 各家应答分别判断，互不借用承诺；不出总体分数，每个验收项单独给结论、适用理由、证据位置与待澄清问题。
- 已发出的会议纪要按发出时间重建当时材料回查，后来的补遗或澄清导致安排失效时给出变更原因；新需求包接入同一项目后可重新比对并对比快照。

### 使用

在项目根目录下运行（命令中的项目目录可放在任意位置）：

```sh
python3 -m acceptance init --project /path/to/proj          # 建项目
python3 -m acceptance ingest --project /path/to/proj --name 首轮材料 --dir materials
python3 -m acceptance evaluate --project /path/to/proj      # 比对并落快照
python3 -m acceptance report --project /path/to/proj        # 条款覆盖意见
python3 -m acceptance report --project /path/to/proj --supplier 折港
python3 -m acceptance minutes --project /path/to/proj       # 纪要回查与变更
python3 -m acceptance snapshots --project /path/to/proj     # 快照列表
python3 -m acceptance diff --project /path/to/proj --a 1 --b 2
```

拿到新的需求包后在同一项目里继续：

```sh
python3 -m acceptance ingest --project /path/to/proj --name 会后补充 --dir /path/to/new-materials
python3 -m acceptance evaluate --project /path/to/proj --label 补充后
python3 -m acceptance diff --project /path/to/proj --a 1 --b 2
```

`tests/fixtures/pkg2/` 是一个补充包样例：补遗把满载工况再改为 70 台（原 60 台安排随之失效），供应商澄清把西区口径签入默认方案（西区转为可验收）。

### 输出结构

报告分六节：现行需求基线（含更正沿革）、分供应商覆盖意见（结论＋证据位置＋适用理由＋验收前提）、可交工程组的验收项（含共享前提分组）、需问清的问题（分问供应商/问采购方）、会议纪要回查与变更（当时依据、当时判断、失效原因）、宣传与意向（不作为验收依据）。证据位置精确到文书编号与原文字符区间，可按原文回查。

### 解析的边界

解析是规则化的确定性解析：数量与单位归一化后比较（0.05 Gbps 即 50 Mbps），统计口径按分位/峰值/均值/窗口内最低值区分，指代（相同上限、同正文口径、均值口径）在供应商全部材料内解析，只写区域不写设施名的句子按条件表的区域归属定位。识别不了的更正句与指代保留为未解析记录，在报告中列出，需人工处理，不静默丢弃。
