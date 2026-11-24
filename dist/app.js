"use strict";

const byId = id => document.getElementById(id);
const fieldNames = {complex:"复几何", differential:"微分几何", algebraic:"代数几何"};
const coverageNames = {pending:"待采集", sample:"已有样本", verified:"目录已对账", limited:"来源受限"};
const statusNames = {unmarked:"待评估", reading:"阅读论文中", planned:"准备联系", contacted:"已联系", replied:"已回复"};
const number = new Intl.NumberFormat("zh-CN");
const primaryRank = window.geometryRanking;
const rankings = window.geometryRankings;
const baseline = {schemaVersion:1, ranking:primaryRank, rankings, schools:window.geometrySchools, people:window.geometryFaculty};
const officialSchools = new Map(baseline.schools.map(school => [school.id, school]));
const privateKey = "geometry-atlas-tracker-v1";
const pageSizes = {faculty:15, schools:20};

let catalog = baseline;
let schools = new Map();
let people = new Map();
let schoolCounts = new Map();
let tracker = readTracker();
let view = "directory";
let facultyPage = 1;
let schoolPage = 1;
let currentFaculty = [];
let noticeTimer;

function node(tag, attributes = {}, ...items) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value != null) element.setAttribute(key, String(value));
  }
  for (const item of items.flat(Infinity)) {
    if (item != null) element.append(item);
  }
  return element;
}

function publicUrl(url) {
  if (typeof url !== "string") return null;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    return null;
  }
}

function external(label, url, className) {
  const href = publicUrl(url);
  return href ? node("a", {href, target:"_blank", rel:"noopener noreferrer", class:className}, label) : null;
}

function button(label, handler, className = "button", attributes = {}) {
  const result = node("button", {type:"button", class:className, ...attributes}, label);
  result.addEventListener("click", handler);
  return result;
}

function readTracker() {
  try {
    const entries = JSON.parse(localStorage.getItem(privateKey) || "[]");
    return new Map(Array.isArray(entries) ? entries : []);
  } catch {
    return new Map();
  }
}

function updateTracker(id, updates) {
  const entry = {...tracker.get(id), ...updates};
  const next = new Map(tracker);
  next.set(id, entry);
  let persisted = true;
  try {
    localStorage.setItem(privateKey, JSON.stringify(Array.from(next)));
  } catch {
    persisted = false;
  }
  tracker = next;
  return persisted;
}

function normalized(text) {
  return String(text ?? "").normalize("NFKD").replace(/\p{M}/gu, "").replace(/[’']/g, "").toLowerCase();
}

function tokens(text) {
  return normalized(text).trim().split(/\s+/).filter(Boolean);
}

function names(person) {
  return [person.nameZh, person.name].filter(Boolean).join(" · ");
}

function displaySchool(school) {
  return school?.nameZh || school?.name || "";
}

function rankText(school) {
  const labels = [];
  if (school.ranks.qs) labels.push(`QS ${school.ranks.qs}`);
  if (school.ranks.gras) labels.push(`软科 ${school.ranks.gras}`);
  return labels;
}

function rankStart(rank) {
  return Number(rank?.match(/\d+/)?.[0] ?? Infinity);
}

function labelCoverage(school) {
  return school.coverage === "pending" && schoolCounts.get(school.id) ? "sample" : school.coverage;
}

function rankedSchool(person, filter = "") {
  return person.affiliations.find(item => item.schoolId === filter)
    ?? person.affiliations.find(item => item.type === "primary")
    ?? person.affiliations[0];
}

function comparableMetrics(person) {
  return (person.metrics ?? []).filter(metric => metric.source === "OpenAlex"
     && metric.articleScope === "OpenAlex type:article"
     && metric.citationScope === "OpenAlex 作者档案累计引用")
    .sort((a, b) => b.checkedAt.localeCompare(a.checkedAt))[0];
}

function countFormat(value, fallback = "待核") {
  return Number.isInteger(value) ? number.format(value) : fallback;
}

function showNotice(message) {
  const output = byId("notice");
  output.textContent = message;
  output.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { output.hidden = true; }, 3200);
}

function setSelectOptions(select, entries) {
  const value = select.value;
  select.replaceChildren(select.options[0], ...entries.map(([id, label]) => node("option", {value:id}, label)));
  if (Array.from(select.options).some(option => option.value === value)) select.value = value;
}

function loadCatalog(next) {
  catalog = next;
  schools = new Map(next.schools.map(school => [school.id, school]));
  people = new Map(next.people.map(person => [person.id, person]));
  schoolCounts = new Map();
  for (const person of next.people) {
    for (const id of new Set(person.affiliations.map(item => item.schoolId))) {
      schoolCounts.set(id, (schoolCounts.get(id) || 0) + 1);
    }
  }
  const cities = Array.from(new Set(next.schools.map(school => school.region))).sort((a,b) => a.localeCompare(b, "zh-CN"));
  setSelectOptions(byId("school-filter"), next.schools.map(school => [school.id, displaySchool(school)]));
  setSelectOptions(byId("region-filter"), cities.map(region => [region, region]));
  setSelectOptions(byId("school-region"), cities.map(region => [region, region]));
  byId("scope-total").textContent = number.format(next.schools.length);
  byId("sampled-total").textContent = number.format(schoolCounts.size);
  byId("faculty-total").textContent = number.format(next.people.length);
  const reviewed = next.schools.filter(item => item.coverage === "verified").length;
  const remaining = next.schools.length - reviewed;
  byId("coverage-text").textContent = `${schoolCounts.size} 所院校有学者档案，${reviewed} 所完成全校名册对账，${remaining} 所仍待对账。`;
  const latest = next.people.map(person => person.checkedAt || "").sort().at(-1);
  if (latest) byId("footer-date").textContent = `资料更新至 ${latest}`;
  updateSavedCount();
  renderCurrent();
}

function updateSavedCount() {
  byId("saved-total").textContent = Array.from(people.keys()).filter(id => tracker.get(id)?.saved).length;
}

function switchView(name, focus = false) {
  view = name;
  for (const nav of document.querySelectorAll("[data-nav]")) {
    nav.toggleAttribute("aria-current", nav.dataset.nav === name);
    if (nav.dataset.nav === name) nav.setAttribute("aria-current", "page");
  }
  byId("directory-view").hidden = name === "schools" || name === "method";
  byId("schools-view").hidden = name !== "schools";
  byId("method-view").hidden = name !== "method";
  byId("coverage").hidden = name === "method";
  renderCurrent();
  if (focus) {
    byId("main").focus({preventScroll:true});
    byId("main").scrollIntoView({block:"start"});
  }
}

function renderCurrent() {
  if (view === "schools") renderSchools();
  if (view === "directory" || view === "saved") renderFaculty();
}

function resetFacultyFilters() {
  for (const id of ["faculty-search", "school-filter", "region-filter"]) byId(id).value = "";
  for (const input of document.querySelectorAll(".filters input")) input.checked = false;
  byId("sort").value = "school";
  facultyPage = 1;
}

function openSchool(id) {
  resetFacultyFilters();
  byId("school-filter").value = id;
  switchView("directory", true);
}

function fieldTag(field) {
  return node("span", {class:`field-tag ${field}`}, fieldNames[field]);
}

function metric(label, value) {
  return node("div", {class:"metric-value"}, node("dt", {}, label), node("dd", {}, countFormat(value, "—")));
}

function makeMetricRow(record) {
  const description = record ? `OpenAlex · ${record.checkedAt}` : "指标待核";
  return node("dl", {class:"row-metrics", "aria-label":"OpenAlex 计量快照"},
    metric("文章", record?.articles),
    metric("引用", record?.citations),
    metric("h 指数", record?.hIndex),
    node("div", {class:"metric-note"}, node("dt", {class:"sr-only"}, "来源日期"), node("dd", {class:"sr-only"}, description),
      node("span", {"aria-hidden":"true"}, description))
  );
}

function card(person, schoolFilter) {
  const affiliation = rankedSchool(person, schoolFilter);
  const school = schools.get(affiliation.schoolId);
  const isSaved = Boolean(tracker.get(person.id)?.saved);
  const label = `${isSaved ? "取消收藏" : "收藏"} ${names(person)}`;
  const profileButton = button(person.nameZh || person.name, () => showProfile(person.id, schoolFilter), "scholar-name", {
    "aria-label":`查看 ${names(person)} 的详情`
  });
  if (person.nameZh) profileButton.append(node("span", {class:"latin-name"}, person.name));
  const status = tracker.get(person.id)?.status;
  const shortLinks = [
    external("个人主页", person.homepage),
    external(person.cvType || "CV", person.cvUrl),
    external("院系任职页", affiliation.url)
  ];
  if (!person.cvUrl) shortLinks.push(node("span", {class:"unavailable"}, "CV 待查"));
  const favorite = button(isSaved ? "★" : "☆", () => {
    const persisted = updateTracker(person.id, {saved:!isSaved});
    updateSavedCount();
    renderFaculty();
    document.getElementById(`save-${person.id}`)?.focus({preventScroll:true});
    showNotice(persisted ? (isSaved ? "已取消收藏" : "已收藏") : "已更新。当前浏览器无法持久保存。");
  }, "save-button", {id:`save-${person.id}`, "aria-label":label, title:label, "aria-pressed":isSaved});
  return node("article", {class:"surface faculty-row"},
    node("div", {class:"scholar"},
      node("span", {class:"avatar", "aria-hidden":"true"}, person.initials || person.name.substring(0,2).toUpperCase()),
      node("div", {class:"scholar-body"},
        profileButton,
        node("p", {class:"association"}, [displaySchool(school), affiliation.department, affiliation.title].filter(Boolean).join(" · ")),
        node("div", {class:"tags"}, person.fields.map(fieldTag), (person.tags ?? []).slice(0,2).map(tag => node("span", {class:"keyword"}, tag))),
        node("div", {class:"quicklinks"}, shortLinks,
          person.recordStatus === "directory" ? node("span", {class:"status sample"}, "目录收录") : null,
          view === "saved" && status && status !== "unmarked" ? node("span", {class:"status sample"}, statusNames[status]) : null)
      )
    ),
    makeMetricRow(comparableMetrics(person)),
    favorite
  );
}

function updateSchoolOverview(id) {
  const panel = byId("school-overview");
  const school = schools.get(id);
  panel.hidden = !school;
  if (!school) return;
  const available = schoolCounts.get(id) || 0;
  const details = [school.name, school.region, ...rankText(school), coverageNames[labelCoverage(school)], `${available} 位已收录`];
  if (school.checkedAt) details.push(`核对 ${school.checkedAt}`);
  panel.replaceChildren(
    node("h3", {}, displaySchool(school)),
    node("p", {}, details.join(" · ")),
    school.coverageNote ? node("p", {}, String(school.coverageNote)) : null,
    node("div", {class:"quicklinks"}, (school.rosterLinks ?? []).map(([title,url]) => external(title,url)),
      Object.keys(school.ranks).map(key => external(rankings[key].title, rankings[key].url)))
  );
}

function renderFaculty() {
  const query = tokens(byId("faculty-search").value);
  const schoolId = byId("school-filter").value;
  const region = byId("region-filter").value;
  const fields = Array.from(document.querySelectorAll('input[name="field"]:checked')).map(input => input.value);
  const onlyCV = byId("cv-filter").checked;
  const onlyMetrics = byId("metrics-filter").checked;
  const sort = byId("sort").value;
  const getRank = person => rankStart(schools.get(rankedSchool(person,schoolId).schoolId)?.rank);
  const getByline = person => {
    const affiliationNames = person.affiliations.flatMap(affiliation => {
      const school = schools.get(affiliation.schoolId);
      return [school?.nameZh, school?.name, school?.aliases, affiliation.department];
    });
    return normalized([names(person), person.aliases, ...person.fields.map(field => fieldNames[field]),
      ...(person.tags ?? []), ...(person.papers ?? []).map(work => work.title), ...affiliationNames].join(" "));
  };
  const results = catalog.people.filter(person => {
    if (view === "saved" && !tracker.get(person.id)?.saved) return false;
    if ((schoolId || region) && !person.affiliations.some(a => (!schoolId || schoolId === a.schoolId) && (!region || schools.get(a.schoolId)?.region === region))) return false;
    if (fields.length && !fields.some(field => person.fields.includes(field))) return false;
    if (onlyCV && !publicUrl(person.cvUrl)) return false;
    if (onlyMetrics && !comparableMetrics(person)) return false;
    if (!query.length) return true;
    const byline = getByline(person);
    return query.every(word => byline.includes(word));
  });
  results.sort((a,b) => {
    const nameCompare = a.name.localeCompare(b.name);
    if (sort === "name") return nameCompare;
    if (sort === "articles" || sort === "citations") {
      return (comparableMetrics(b)?.[sort] ?? -1) - (comparableMetrics(a)?.[sort] ?? -1) || nameCompare;
    }
    return getRank(a) - getRank(b) || nameCompare;
  });
  currentFaculty = results;
  byId("directory-heading").textContent = view === "saved" ? "已收藏学者" : "学者目录";
  byId("directory-count").textContent = `${number.format(results.length)} 位${fields.length > 1 ? " · 匹配任一所选方向" : ""}`;
  byId("export-csv").disabled = results.length === 0;
  updateSchoolOverview(schoolId);
  facultyPage = validPage(facultyPage, results.length, pageSizes.faculty);
  const start = (facultyPage - 1) * pageSizes.faculty;
  const list = byId("faculty-list");
  if (results.length) {
    list.replaceChildren(...results.slice(start,start + pageSizes.faculty).map(person => card(person, schoolId)));
  } else {
    const pending = schoolId && schools.get(schoolId)?.coverage !== "verified" && !schoolCounts.get(schoolId);
    const title = pending ? "此校还没有学者记录" : view === "saved" && !Array.from(tracker.values()).some(entry => entry.saved) ? "还没有收藏" : "当前筛选没有结果";
    const explanation = pending ? "可在学校索引跟踪收录进度，或导入已核对的新批次。" : view === "saved" ? "在学者目录可点击星标收藏，也可以调整当前筛选。" : "可以清空筛选，或者试试其他关键词。";
    const reset = button(pending ? "返回学校索引" : view === "saved" ? "浏览学者目录" : "清空筛选", () => {
      resetFacultyFilters();
      switchView(pending ? "schools" : "directory");
    });
    list.replaceChildren(node("article",{class:"surface empty"}, node("h3", {}, title), node("p", {}, explanation), reset));
  }
  renderPagination("faculty-pages", facultyPage, results.length, pageSizes.faculty, next => {
    facultyPage = next;
    renderFaculty();
    byId("directory-heading").scrollIntoView({block:"start"});
  });
}

function validPage(page, count, size) {
  return Math.max(1,Math.min(page,Math.ceil(count / size)));
}

function renderPagination(id, page, total, size, onPage) {
  const target = byId(id);
  const last = Math.ceil(total / size);
  target.replaceChildren();
  if (last <= 1) return;
  const prev = button("上一页", () => onPage(page-1));
  const next = button("下一页", () => onPage(page+1));
  prev.disabled = page === 1;
  next.disabled = page === last;
  target.append(prev, node("span", {}, `第 ${page} / ${last} 页`), next);
}

function renderSchools() {
  const query = tokens(byId("school-search").value);
  const region = byId("school-region").value;
  const coverage = byId("coverage-filter").value;
  const ranking = byId("ranking-filter").value;
  const results = catalog.schools.filter(school => {
    if (region && school.region !== region) return false;
    if (coverage && labelCoverage(school) !== coverage) return false;
    if (ranking && !school.ranks[ranking]) return false;
    const byline = normalized([school.name, school.nameZh, school.aliases, school.region].join(" "));
    return query.every(word => byline.includes(word));
  });
  if (ranking) results.sort((a,b) => rankStart(a.ranks[ranking]) - rankStart(b.ranks[ranking]));
  byId("school-count").textContent = `${results.length} 所院校`;
  schoolPage = validPage(schoolPage, results.length, pageSizes.schools);
  const start = (schoolPage - 1) * pageSizes.schools;
  const list = byId("school-list");
  if (!results.length) {
    list.replaceChildren(node("div",{class:"empty"}, node("h3",{},"当前筛选没有学校"),node("p",{},"试试校名简称或其他地区。")));
  } else {
    const heading = node("div",{class:"school-row header-row"}, node("span",{},"名次"),node("span",{},"学校"),node("span",{class:"region-cell"},"地区"),node("span",{},"进度"),node("span",{class:"count-cell"},"学者"));
    const rows = results.slice(start,start + pageSizes.schools).map(school => {
      const state = labelCoverage(school);
      const row = button("", () => openSchool(school.id), "school-row", {"aria-label":`查看${displaySchool(school)}，${coverageNames[state]}`});
      row.append(node("span",{class:"rank"},rankText(school).map(label => node("span",{class:"rank-line"},label))),node("span",{},node("strong",{},displaySchool(school)),
        school.nameZh ? node("span",{class:"name-en",lang:"en"},school.name) : null),
        node("span",{class:"region-cell"},school.region),node("span",{class:`status ${state}`},coverageNames[state]),
        node("span",{class:"count-cell"}, countFormat(schoolCounts.get(school.id) || 0)));
      return row;
    });
    list.replaceChildren(heading, ...rows);
  }
  renderPagination("school-pages", schoolPage, results.length, pageSizes.schools, next => {
    schoolPage = next;
    renderSchools();
    byId("schools-heading").scrollIntoView({block:"start"});
  });
}

function detailSection(title, ...content) {
  return node("section",{class:"detail-section"},node("h3",{},title),content);
}

function showProfile(id, schoolFilter) {
  const person = people.get(id);
  const affiliation = rankedSchool(person, schoolFilter);
  const dialog = byId("profile-dialog");
  const saved = tracker.get(id) ?? {};
  const header = node("div",{class:"detail-header"},
    node("h2",{id:"profile-name"},names(person)),
    node("p",{class:"detail-subtitle"},[displaySchool(schools.get(affiliation.schoolId)),affiliation.department,affiliation.title].filter(Boolean).join(" · ")),
    node("div",{class:"tags"},person.fields.map(fieldTag),(person.tags ?? []).map(tag => node("span",{class:"keyword"},tag)))
  );
  const profiles = detailSection("主页、任职与 CV",
    node("div",{class:"detail-links"},
      external("个人主页",person.homepage,"button"),
      external(person.cvType || "公开 CV",person.cvUrl,"button"),
      external("研究简介",person.bioUrl,"button"),
      external("发表列表",person.publicationsUrl,"button")),
    node("ul",{},person.affiliations.map(item => node("li",{},
      external([displaySchool(schools.get(item.schoolId)),item.department,item.title].filter(Boolean).join(" · "),item.url),
      item.type && item.type !== "primary" ? `（${item.type}）` : "",
      item.checkedAt ? node("small",{},` · 核对 ${item.checkedAt}`) : null
    ))),
    !person.homepage ? node("p",{},node("small",{},person.homepageStatus || "个人主页待核。")) : null,
    !person.cvUrl ? node("p",{},node("small",{},person.cvStatus || "独立 CV 待核。")) : null
  );
  const papers = detailSection("代表作与研究联系",
    person.papers?.length
      ? node("ul",{},person.papers.map(paper => {
        const details = [paper.type, paper.year].filter(Boolean).join(" · ");
        return node("li",{},external(paper.title,paper.url),details ? ` · ${details}` : "",
          paper.relation ? node("div",{},paper.relation) : null);
      }))
      : node("p",{},"代表作待补充。"),
    person.relevance ? node("p",{},person.relevance) : null,
    person.directoryEvidence?.length
      ? node("ul",{},person.directoryEvidence.map(item => node("li",{},item.text," ",external("目录来源",item.url))))
      : null
  );
  const snapshots = (person.metrics ?? []).slice().sort((a,b) => b.checkedAt.localeCompare(a.checkedAt));
  const displayedMetrics = snapshots.map(record => node("div",{class:"metric-block"},
    node("p",{class:"metric-stamp"},`${record.source} · ${record.checkedAt}`),
    node("dl",{class:"detail-metrics"},metric("文章",record.articles),metric("收录成果",record.works),metric("引用",record.citations),metric("h 指数",record.hIndex)),
    node("div",{class:"quicklinks"},
      external("作者档案",record.url), external("文章计数原始查询",record.articleApiUrl), external("作者计量原始查询",record.authorApiUrl), external("ORCID",record.orcid)),
    record.articleScope ? node("p",{},node("small",{},`文章口径 ${record.articleScope}。引用口径 ${record.citationScope || "待补充"}。`)) : null
  ));
  const counts = (person.publicationCounts ?? []).map(record => node("li",{},
    `${countFormat(record.value)}${record.lowerBound ? "+" : ""} · ${record.scope} · 核对 ${record.checkedAt} `,
    external("机构或作者来源", record.url)));
  const metrics = detailSection("计量与作者核验",
    counts.length ? node("ul",{},counts) : node("p",{},"机构或作者披露的论文数待核。"),
    displayedMetrics.length ? displayedMetrics : node("p",{},"OpenAlex 文章数和引用量待核。"),
    person.identityNote ? node("p",{},person.identityNote) : null,
    external("查看待复核档案",person.identityUrl)
  );
  const status = node("select", {id:"contact-status"}, Object.entries(statusNames).map(([value,label]) => node("option",{value},label)));
  status.value = saved.status ?? "unmarked";
  const note = node("textarea", {id:"contact-note", maxlength:3000, placeholder:"记录想讨论的论文、问题或下一步"});
  note.value = saved.note ?? "";
  const feedback = node("span",{class:"metric-stamp",role:"status"});
  const form = node("div",{class:"note-form"},
    node("label",{for:"contact-status"},"联系状态",status),
    node("label",{for:"contact-note"},"私人备注",note),
    button("保存到收藏",() => {
      const persisted = updateTracker(id,{saved:true,status:status.value,note:note.value.trim()});
      updateSavedCount();
      renderCurrent();
      feedback.textContent = persisted ? "已保存到此浏览器。" : "已保存到本次会话。当前浏览器无法持久保存。";
    },"button button-primary"),feedback);
  const opportunities = person.opportunities?.length
    ? node("ul",{},person.opportunities.map(item => node("li",{},external(item.label,item.url),` · ${[item.type,item.status,item.deadline,item.checkedAt].filter(Boolean).join(" · ")}`)))
    : node("p",{},"访问或博士后机会待核。可从院系任职页查看联系与项目入口。");
  byId("profile-content").replaceChildren(header, profiles, papers, metrics, detailSection("机会与联系记录", opportunities, form));
  dialog.showModal();
}

function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data],{type}));
  const link = node("a",{href:url,download:name});
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value) {
  let text = String(value ?? "");
  if (typeof value === "string" && /^[\s]*[=+@-]|^[\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g,'""') + '"';
}

function exportCsv() {
  const header = ["姓名","中文名","学校","部门","任职","公示任职链接","方向","关键词","个人主页","CV","代表论文","文章数","成果数","累计引用","h 指数","指标来源","作者 ID","数据日期","指标口径","身份核对说明"];
  const rows = currentFaculty.map(person => {
    const affiliation = rankedSchool(person,byId("school-filter").value);
    const m = comparableMetrics(person);
    return [person.name,person.nameZh,displaySchool(schools.get(affiliation.schoolId)),affiliation.department,affiliation.title,affiliation.url,
      person.fields.map(field => fieldNames[field]).join(" / "),person.tags?.join(" / "),person.homepage,person.cvUrl,
      person.papers?.map(work => work.url).join(" | "),m?.articles,m?.works,m?.citations,m?.hIndex,m?.source,m?.authorId,m?.checkedAt,m?.articleScope,person.identityNote];
  });
  const csv = "\uFEFF" + [header,...rows].map(row => row.map(csvCell).join(",")).join("\r\n");
  download("geometry-faculty.csv",csv,"text/csv;charset=utf-8");
  showNotice(`已导出 ${rows.length} 位学者`);
}

function database() {
  return new Promise((resolve,reject) => {
    if (!window.indexedDB) return reject(new Error("浏览器未启用 IndexedDB。"));
    const request = indexedDB.open("geometry-faculty-atlas",1);
    request.onupgradeneeded = () => request.result.createObjectStore("catalog");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("其他标签页占用了数据库。"));
  });
}

async function readCatalog() {
  const db = await database();
  try {
    return await new Promise((resolve,reject) => {
      const request = db.transaction("catalog").objectStore("catalog").get("active");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

async function writeCatalog(value) {
  const db = await database();
  try {
    await new Promise((resolve,reject) => {
      const transaction = db.transaction("catalog","readwrite");
      transaction.objectStore("catalog").put(value,"active");
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

function assert(condition,message) {
  if (!condition) throw new Error(message);
}

function safeRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function mergeCatalog(existing, incoming) {
  assert(safeRecord(incoming) && incoming.schemaVersion === 1 && Array.isArray(incoming.schools) && Array.isArray(incoming.people), "需要 schemaVersion 1 的 JSON，包含 schools 和 people 数组。");
  assert(!incoming.ranking || (incoming.ranking.year === primaryRank.year && incoming.ranking.subject === primaryRank.subject && incoming.ranking.url === primaryRank.url), "该文件的院校范围与当前的 2026 数学榜不一致。");
  const nextSchools = new Map(existing.schools.map(school => [school.id,school]));
  const schoolIds = new Set();
  for (const item of incoming.schools) {
    assert(safeRecord(item) && officialSchools.has(item.id) && !schoolIds.has(item.id), "学校 ID 未收录或在导入文件中重复。");
    schoolIds.add(item.id);
    const official = officialSchools.get(item.id);
    const school = {...nextSchools.get(item.id),...item,id:official.id,rank:official.rank,ranks:official.ranks,region:official.region,name:official.name};
    assert(Object.hasOwn(coverageNames,school.coverage) && Array.isArray(school.rosterLinks) && school.rosterLinks.every(pair => Array.isArray(pair) && typeof pair[0] === "string" && publicUrl(pair[1])), `${item.id} 的对账状态或目录网址有误。`);
    nextSchools.set(school.id,school);
  }
  const nextPeople = new Map(existing.people.map(person => [person.id,person]));
  const personIds = new Set();
  const knownIdentities = new Map();
  for (const item of incoming.people) {
    assert(safeRecord(item) && typeof item.id === "string" && /^[a-z][a-z0-9-]{0,100}$/.test(item.id) && !personIds.has(item.id), "学者 ID 格式有误或在导入文件中重复。");
    personIds.add(item.id);
    const previous = nextPeople.get(item.id);
    const person = {...previous,...item};
    assert(typeof person.name === "string" && person.name.trim().length > 0, `${item.id} 缺少姓名。`);
    assert(Array.isArray(person.affiliations) && person.affiliations.length > 0 && person.affiliations.every(item => safeRecord(item) && nextSchools.has(item.schoolId) && publicUrl(item.url)), `${item.id} 的任职学校或来源网址有误。`);
    assert(Array.isArray(person.fields) && person.fields.every(field => Object.hasOwn(fieldNames,field)), `${item.id} 的方向标签需使用约定的代码。`);
    assert(!person.tags || (Array.isArray(person.tags) && person.tags.every(tag => typeof tag === "string")), `${item.id} 的关键词格式有误。`);
    assert(!person.papers || (Array.isArray(person.papers) && person.papers.every(paper => safeRecord(paper) && typeof paper.title === "string" && publicUrl(paper.url))), `${item.id} 的论文来源有误。`);
    assert(!item.publicationCounts || (Array.isArray(item.publicationCounts) && item.publicationCounts.every(record =>
      safeRecord(record) && Number.isSafeInteger(record.value) && record.value >= 0
      && (record.lowerBound === undefined || typeof record.lowerBound === "boolean")
      && typeof record.scope === "string" && record.scope.trim()
      && /^\d{4}-\d{2}-\d{2}$/.test(record.checkedAt) && publicUrl(record.url))), `${item.id} 的论文数缺少口径、日期或来源。`);
    person.publicationCounts = Array.from(new Map([...(previous?.publicationCounts ?? []), ...(item.publicationCounts ?? [])]
      .map(record => [JSON.stringify([record.url, record.scope, record.checkedAt]),record])).values());
    assert(!person.directoryEvidence || (Array.isArray(person.directoryEvidence) && person.directoryEvidence.every(entry => safeRecord(entry) && typeof entry.text === "string" && publicUrl(entry.url))), `${item.id} 的方向来源有误。`);
    assert(!person.opportunities || (Array.isArray(person.opportunities) && person.opportunities.every(op => safeRecord(op) && typeof op.label === "string" && publicUrl(op.url))), `${item.id} 的机会来源有误。`);
    assert(!item.metrics || Array.isArray(item.metrics), `${item.id} 的计量记录需要是数组。`);
    const records = new Map();
    for (const record of [...(previous?.metrics ?? []), ...(item.metrics ?? [])]) {
      assert(safeRecord(record) && typeof record.source === "string" && typeof record.authorId === "string" && typeof record.checkedAt === "string" && /^\d{4}-\d{2}-\d{2}$/.test(record.checkedAt) && publicUrl(record.url), `${item.id} 的计量记录缺少作者 ID、来源网址或日期。`);
      assert(["articles","works","citations","hIndex"].every(key => record[key] == null || (Number.isSafeInteger(record[key]) && record[key] >= 0)), `${item.id} 的指标必须为非负整数或空值。`);
      records.set(`${record.source}|${record.authorId}|${record.checkedAt}`,record);
    }
    person.metrics = Array.from(records.values());
    nextPeople.set(person.id,person);
  }
  for (const person of nextPeople.values()) {
    for (const record of person.metrics ?? []) {
      for (const identity of [`${record.source}|${record.authorId}`, publicUrl(record.orcid)].filter(Boolean)) {
        assert(!knownIdentities.has(identity) || knownIdentities.get(identity) === person.id, "两个学者 ID 使用了同一作者档案。请先核对合并。");
        knownIdentities.set(identity,person.id);
      }
    }
  }
  return {schemaVersion:1, ranking:primaryRank, rankings, schools:Array.from(nextSchools.values()), people:Array.from(nextPeople.values())};
}

async function onImport() {
  const input = byId("catalog-file");
  const file = input.files[0];
  if (!file) return;
  input.value = "";
  const status = byId("import-status");
  status.textContent = "正在检查文件…";
  byId("import-json").disabled = true;
  try {
    const incoming = JSON.parse((await file.text()).replace(/^\uFEFF/,""));
    const merged = mergeCatalog(catalog,incoming);
    let persisted = true;
    try {
      await writeCatalog(merged);
    } catch {
      persisted = false;
    }
    loadCatalog(merged);
    status.textContent = `已合并 ${incoming.schools.length} 所学校的资料和 ${incoming.people.length} 位学者的记录。${persisted ? "" : " 本次浏览会话可用，请导出 JSON 留存。"}`;
  } catch (error) {
    status.textContent = `导入未完成。 ${error.message || "请检查文件格式。"}`;
  } finally {
    byId("import-json").disabled = false;
  }
}

function exportCatalog() {
  download("geometry-faculty-catalog.json",JSON.stringify(catalog,null,2),"application/json;charset=utf-8");
}

for (const control of document.querySelectorAll("[data-view]")) {
  control.addEventListener("click", () => {
    if (control.classList.contains("brand")) resetFacultyFilters();
    if (control.dataset.view === "saved") resetFacultyFilters();
    switchView(control.dataset.view);
  });
}
for (const control of document.querySelectorAll(".filters input, .filters select, #sort")) {
  control.addEventListener("change", () => { facultyPage = 1; renderFaculty(); });
}
byId("faculty-search").addEventListener("input", () => { facultyPage = 1; renderFaculty(); });
for (const control of document.querySelectorAll("[data-keyword]")) {
  control.addEventListener("click", () => {
    byId("faculty-search").value = control.dataset.keyword;
    facultyPage = 1;
    renderFaculty();
  });
}
byId("reset-filters").addEventListener("click", () => { resetFacultyFilters(); renderFaculty(); });
for (const id of ["school-search", "school-region", "ranking-filter", "coverage-filter"]) {
  byId(id).addEventListener(id === "school-search" ? "input" : "change", () => { schoolPage = 1; renderSchools(); });
}
for (const close of document.querySelectorAll("[data-close]")) {
  close.addEventListener("click", () => close.closest("dialog").close());
}
byId("data-button").addEventListener("click", () => byId("data-dialog").showModal());
byId("export-csv").addEventListener("click",exportCsv);
byId("export-json").addEventListener("click",exportCatalog);
byId("export-json-method").addEventListener("click",exportCatalog);
byId("import-json").addEventListener("click",() => byId("catalog-file").click());
byId("catalog-file").addEventListener("change",onImport);
byId("export-saved").addEventListener("click",() => {
  const entries = Array.from(tracker).map(([id,value]) => ({id,name:people.get(id)?.name,...value}));
  download("geometry-faculty-private-notes.json",JSON.stringify(entries,null,2),"application/json;charset=utf-8");
});

const bundledCatalog = window.geometryCollection ? mergeCatalog(baseline, window.geometryCollection) : baseline;
loadCatalog(bundledCatalog);
readCatalog().then(value => {
  if (value) loadCatalog(mergeCatalog(bundledCatalog,value));
}).catch(() => {
  // The bundled directory stays usable on browsers without local database access.
});
