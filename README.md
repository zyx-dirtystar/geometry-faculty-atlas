# 几何学者索引

[打开在线学者目录](https://zyx-dirtystar.github.io/geometry-faculty-atlas/)。每次更新 `main` 分支时，GitHub Pages 会重新部署 `dist/` 中的网页。

打开 `dist/index.html` 可浏览目录。用 Node.js 执行 `node build-offline.mjs` 可生成便于转发的单文件网页 `geometry-faculty-atlas.html`。外部来源链接需要联网。协作和提交流程见 [贡献说明](CONTRIBUTING.md)。

学校池合并 2026 年软科 GRAS 数学前百与 QS 数学名次公开且达到前 160 的学校。QS 在并列第 150 位后使用 151–200 区间，因此在学校索引单列这一档的候选，并保留两个榜单的原始名次。覆盖情况见 [采集进度](collector/PROGRESS.md)，个人字段缺口见 [字段待核表](collector/field-review.csv)。

## 继续运行

可以在 Codex 桌面、终端或 VS Code 终端操作同一个项目。仓库中的 `collector/checkpoint.json` 保存可共享的结构化进度。新的检出从该文件恢复本地 SQLite。原始网页缓存与本地数据库在协作者自己的工作目录生成。打开项目的新会话先读 `AGENTS.md` 和 `collector/PROGRESS.md`。

```powershell
python -m pip install -r requirements.txt
python -X utf8 collector/run.py --offline
python -X utf8 collector/run.py --school pku --profiles
python -X utf8 collector/run.py --profiles --metrics
```

第一条用已有快照重建网页。后两条读取已登记的公开站点。命令使用带 `lxml` 的 Python 和 Node.js。OpenAlex 请求受来源的访问额度约束，以已核对的论文 DOI 为入口。通过批次样本确认作者档案后，将该学者 ID 与 OpenAlex ID 写入 `collector/metric-review.json` 的 `accepted` 项，重建时才会将数字写入网站。

新增学校先查实公开院系目录，并登记到 `collector/rosters.json`。目录结构有差异时，在 `collector/roster_parsers.py` 增加该来源的提取方法，再运行采集。源页面故障、没有提取到记录和需要判断任职的条目分别在进度表和 `collector/review-queue.csv` 中保留。目录、研究分组和相关教学单位逐一对账之后，再更新校级完成状态。

逐人复核后的主页、CV、任职和研究方向可补入 `collector/verified-profiles.json`，并附官方任职及研究来源。进度表的「主页 / CV / 指标」统计的是网页已收录且该字段有来源的学者。个人主页、CV、论文数及引用量的空缺在复核表里标为「待核」。

## 采集与导入

1. 用「管理数据 → 导出目录 JSON」取得现有学校 ID 和样本字段。
2. 按提示词遍历学校目录并核查研究方向和作者身份。新批次使用相同学校 ID。导入文件可只含本批修改过的学校和学者。
3. 在「管理数据」中导入批次。相同学者 ID 会更新，已保存的计量快照会按数据源、作者 ID、日期合并。程序会更新 `dist/collection.js`、`collector/catalog-batch.json` 和相应学校的覆盖记录。

导入文件要求顶层 `schemaVersion: 1`、`schools: []` 和 `people: []`。如提供 `ranking`，其来源、年份和学科须与现有数据一致。

- `schools[].id` 对应学校池。可更新 `rosterLinks`（每项是 `[名称, URL]`）、`checkedAt` 与 `coverage`（`pending`、`sample`、`verified`、`limited`）。目录对账记录可用 `coverageNote` 描述，并附目录来源。
- `people[].id` 为稳定的小写英文标识。新记录包含 `name`、`affiliations`（每项至少有 `schoolId` 与公开任职 `url`）、`fields`（`complex`、`differential`、`algebraic`）。可添加 `nameZh`、`aliases`、`homepage`、`cvUrl`、`tags`、`checkedAt`、`identityNote`、`papers`、`opportunities`。
- `papers[]` 保存 `title`、`url` 和可选的 `year`。`opportunities[]` 至少含 `label` 与官方 `url`，可附 `type`、`status`、`deadline`、`checkedAt`。
- `metrics[]` 需要 `source`、`authorId`、`url`、`checkedAt`。数字字段为 `articles`、`works`、`citations`、`hIndex`。可排序的 OpenAlex 快照使用 `articleScope: "OpenAlex type:article"` 与 `citationScope: "OpenAlex 作者档案累计引用"`。

目录 JSON 和筛选结果 CSV 只包含公开学术记录。站内「导出收藏与备注」单独备份私人记录。导入和收藏的数据保存在当前浏览器，同一链接在其他浏览器打开时从站点随附的数据开始。
