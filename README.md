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
