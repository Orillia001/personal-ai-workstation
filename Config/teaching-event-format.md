# 学习事件格式

仅在评阅后写入事件时读取。本文件和事件都留在后台。

自述已有基础：
```json
{"node_id":"当前知识点ID","kind":"self_report"}
```

练习评阅：
```json
{"node_id":"当前知识点ID","kind":"practice","assessment_type":"concept","question":"实际题目","answer":"学习者实际作答","feedback":"具体评阅依据","score":0.8,"error":"不超过160字的错因摘要"}
```

assessment_type取concept、calculation或structure。score为0到1的比例，须由实际作答及评阅支持；概念题使用concept_threshold，计算和结构题使用practice_threshold。单次通过只记review_due，未通过记in_progress；不自动登记长期掌握。自行补造题目、答案或分数不能作为学习证据。

调用：`./ws.ps1 teach-record <课程ID> 事件JSON路径`。只记录当前选定知识点；切换使用teach-select。原有学习证据和正式义务继续独立保存，不由事件覆盖。
