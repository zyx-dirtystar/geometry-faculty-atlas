# 贡献指南

打开 [学校覆盖进度](collector/PROGRESS.md)，选择一所学校或一个待复核的问题。可以在 [复核队列](collector/review-queue.csv) 找到来源和待确认的学者。多人同时工作时，可在 GitHub Issues 中登记学校和检查范围。

1. 新开分支，用学校的公开院系目录、研究组和个人网站核对任职和方向。把新增目录和提取方法放到 `collector/rosters.json` 和 `collector/roster_parsers.py`。
2. 从项目目录运行 `python -X utf8 collector/run.py --school <学校ID> --profiles`。若要复核引用和论文数，先核对论文 DOI、作者档案及名字相同的候选。在 `collector/metric-review.json` 记录确认结果。
3. 检查 `collector/PROGRESS.md`、`collector/checkpoint.json`、目录数据和网页。保留其他学校的已有记录。针对同一所学校从最新仓库版本开始工作，有助于减少采集结果冲突。
4. 提交 Pull Request 并附官网依据、增加的记录数和剩余待核项。合并前核对同名、双聘、荣休、空值和引用口径。

可以直接从新检出的项目执行 `python -X utf8 collector/run.py --offline` 验证恢复后的目录。个人备注与联系人状态由各自的浏览器保存。原始网页缓存、私人备注导出、API 凭据和本地部署配置保存在本机。
