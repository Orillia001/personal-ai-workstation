# Triage labels

采用 Matt 默认标签；本地任务的分流字段沿用相同字符串。

| Matt角色 | 本地标签 | 含义 |
| --- | --- | --- |
| needs-triage | needs-triage | 等待评估 |
| needs-info | needs-info | 缺少外部信息 |
| ready-for-agent | ready-for-agent | 需求明确，可执行 |
| ready-for-human | ready-for-human | 需要人工处理 |
| wontfix | wontfix | 本轮不执行 |

to-tickets 产生的明确任务直接使用 ready-for-agent；原始缺陷或未整理的外部请求才进入 triage。
