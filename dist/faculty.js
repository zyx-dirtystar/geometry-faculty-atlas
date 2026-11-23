(() => {
  const checkedAt = "2026-11-23";
  const affiliation = (schoolId, department, title, url) => ({schoolId, department, title, url, type:"primary", checkedAt});
  const work = (title, year, url) => ({title, year, url});
  const openAlex = (authorId, orcid, articles, works, citations, hIndex) => [{
    source:"OpenAlex", authorId, orcid:`https://orcid.org/${orcid}`,
    url:`https://openalex.org/authors/${authorId}`,
    authorApiUrl:`https://api.openalex.org/authors/${authorId}`,
    articleApiUrl:`https://api.openalex.org/works?filter=authorships.author.id:${authorId},type:article&per_page=1&select=id`,
    checkedAt, articles, works, citations, hIndex, articleScope:"OpenAlex type:article",
    citationScope:"OpenAlex 作者档案累计引用"
  }];

  window.geometryFaculty = [
    {
      id:"chenyang-xu", name:"Chenyang Xu", nameZh:"许晨阳", initials:"CX",
      affiliations:[affiliation("princeton","数学系","教授","https://www.math.princeton.edu/people/chenyang-xu")],
      fields:["algebraic"], tags:["双有理几何","Fano","K-稳定性","奇点","高维代数几何"],
      homepage:"https://web.math.princeton.edu/~chenyang/", cvUrl:null, cvStatus:"已核对个人主页，暂未定位独立 CV。",
      bioUrl:"https://www.math.princeton.edu/news/department-welcomes-chenyang-xu-professor-mathematics",
      publicationsUrl:"https://web.math.princeton.edu/~chenyang/",
      metrics:openAlex("A5102008315","0000-0001-6627-3069",55,120,4549,35),
      identityNote:"用 Princeton 任职、Fano K-稳定性论文和 Annals 的作者信息核对。索引里还有多位不同领域的同名作者。",
      papers:[work("Special test configuration and K-stability of Fano varieties",2014,"https://doi.org/10.4007/annals.2014.180.1.4"),
        work("Finite generation for valuations computing stability thresholds and applications to K-stability",2022,"https://doi.org/10.4007/annals.2022.196.2.2")],
      relevance:"如果需要讨论 Fano 紧化的代数侧，可以从 K-稳定性、奇点和双有理方法切入。"
    },
    {
      id:"janos-kollar", name:"János Kollár", initials:"JK",
      affiliations:[affiliation("princeton","数学系","教授","https://www.math.princeton.edu/people/janos-kollar")],
      fields:["algebraic"], tags:["双有理几何","奇点","模空间","极小模型"],
      homepage:"https://web.math.princeton.edu/~kollar/", cvUrl:"https://web.math.princeton.edu/~kollar/FromMyHomePage/janosvita2022.pdf",
      publicationsUrl:"https://web.math.princeton.edu/~kollar/",
      metrics:[], identityNote:"候选主档含同名作者的金属表面能论文，另有拆分档案。累计指标暂留待核。",
      identityUrl:"https://openalex.org/authors/A5051485543",
      papers:[work("Families of Varieties of General Type",2023,"https://doi.org/10.1017/9781009346115"),work("Birational Geometry of Algebraic Varieties",1998,"https://doi.org/10.1017/CBO9780511662560")],
      relevance:"双有理几何、奇点和配对的代数工具，适合核对补空间问题的代数前提。"
    },
    {
      id:"ravi-vakil", name:"Ravi Vakil", initials:"RV",
      affiliations:[affiliation("stanford","数学系","教授","https://mathematics.stanford.edu/people/ravi-vakil")],
      fields:["algebraic"], tags:["曲线模空间","枚举几何","形变理论","代数叠"],
      homepage:"https://math.stanford.edu/~vakil/", cvUrl:null, cvStatus:"已核对个人主页，暂未定位独立 CV。",
      bioUrl:"https://profiles.stanford.edu/ravi-vakil?tab=bio", publicationsUrl:"https://math.stanford.edu/~vakil/preprints.html",
      metrics:openAlex("A5013856193","0000-0001-8506-270X",56,159,3598,26),
      identityNote:"用 Stanford 任职和形变、曲线模空间的两篇作者论文核对。",
      papers:[work("Murphy’s law in algebraic geometry: Badly-behaved deformation spaces",2006,"https://doi.org/10.1007/s00222-005-0481-9"),
        work("Relative virtual localization and vanishing of tautological classes on moduli spaces of curves",2005,"https://doi.org/10.1215/S0012-7094-05-13011-3")],
      relevance:"曲线模空间与形变理论可提供平面三次曲线后续问题的代数背景。"
    },
    {
      id:"rafe-mazzeo", name:"Rafe Mazzeo", initials:"RM",
      affiliations:[affiliation("stanford","数学系","教授","https://mathematics.stanford.edu/people/rafe-mazzeo")],
      fields:["differential","complex"], tags:["几何分析","Kähler","奇异度量","椭圆 PDE"],
      homepage:null, homepageStatus:"院系主页列出个人站地址，直接访问暂未成功。",
      bioUrl:"https://profiles.stanford.edu/rafe-mazzeo",
      cvUrl:"https://cap.stanford.edu/profiles/viewCV?facultyId=10624&name=Rafe_Mazzeo",
      publicationsUrl:"https://profiles.stanford.edu/rafe-mazzeo",
      metrics:openAlex("A5087642309","0000-0001-7058-3246",115,206,6881,45),
      identityNote:"用 Stanford 任职、边算子论文和带边缘奇性的 Kähler–Einstein 度量论文核对。",
      papers:[work("Kähler–Einstein metrics with edge singularities",2016,"https://doi.org/10.4007/annals.2016.183.1.3")],
      relevance:"与边界附近的奇异 Kähler 度量及几何分析方法有关。"
    },
    {
      id:"chi-li", name:"Chi Li", nameZh:"李驰", initials:"CL",
      affiliations:[affiliation("rutgers","数学系","教授","https://www.math.rutgers.edu/people/department-directory/detail/344-department-directory/1957-li-chi")],
      fields:["complex","differential","algebraic"], tags:["紧化","Reeb 动力学","辛同调","Kähler","Fano","K-稳定性"],
      homepage:"https://sites.math.rutgers.edu/~cl1412/", cvUrl:"https://sites.math.rutgers.edu/~cl1412/ChiLi-CV.pdf",
      publicationsUrl:"https://sites.math.rutgers.edu/~cl1412/",
      metrics:openAlex("A5100351591","0000-0001-8725-9389",28,41,1840,22),
      identityNote:"由《Kähler compactification…》的出版 DOI 反查作者 ID，并用论文所列的 Rutgers 机构核对。名字检索的高位候选属于其他领域。",
      papers:[work("Kähler compactification of ℂⁿ and Reeb dynamics",2025,"https://doi.org/10.1007/s00222-025-01377-2"),
        work("Special test configuration and K-stability of Fano varieties",2014,"https://doi.org/10.4007/annals.2014.180.1.4")],
      relevance:"Li–Zhou 的工作与 Henry 的紧化问题在 Reeb 动力学和辛同调方法上直接相邻，适合带着一条具体技术依赖阅读。"
    },
    {
      id:"daniel-huybrechts", name:"Daniel Huybrechts", initials:"DH",
      affiliations:[affiliation("bonn","数学研究所","教授","https://www.mathematics.uni-bonn.de/en/people/people")],
      fields:["complex","algebraic"], tags:["K3 曲面","超 Kähler","模空间","Hodge 理论","导出范畴"],
      homepage:"https://www.math.uni-bonn.de/people/huybrech/?language=en", cvUrl:"https://www.math.uni-bonn.de/people/huybrech/CVHuybrechts.pdf",
      publicationsUrl:"https://www.math.uni-bonn.de/people/huybrech/?language=en",
      metrics:openAlex("A5010170221","0000-0003-4397-4836",53,177,8815,33),
      identityNote:"用 Bonn 任职、层模空间与 K3／Lagrangian 纤维化作者记录核对。",
      papers:[work("Lagrangian Fibrations",2022,"https://doi.org/10.1007/s00032-022-00349-y"),
        work("Splitting unramified Brauer classes by abelian torsors and the period-index problem",2025,"https://doi.org/10.1007/s00208-025-03161-2")],
      relevance:"适合了解 K3、超 Kähler 边界和周期／模空间工具的研究环境。"
    },
    {
      id:"ursula-hamenstaedt", name:"Ursula Hamenstädt", initials:"UH",
      affiliations:[affiliation("bonn","数学研究所","教授","https://www.uni-bonn.de/de/forschung-lehre/forschungsprofil/transdisziplinaere-forschungsbereiche/modelling/mitgliederverzeichnis/ursula-hamenstaedt")],
      fields:["differential"], tags:["负曲率","Teichmüller 理论","测地流","几何拓扑"],
      homepage:"https://www.math.uni-bonn.de/people/ursula/", cvUrl:null, cvStatus:"已核对个人主页，暂未定位可独立打开的 CV。",
      bioUrl:"https://www.leopoldina.org/en/members/member-list/detail/ursula-hamenstaedt",
      publicationsUrl:"https://www.math.uni-bonn.de/people/ursula/",
      metrics:openAlex("A5005525039","0000-0001-5417-1460",63,110,1508,21),
      identityNote:"用 Bonn 任职、测地流和映射类群论文核对带 ORCID 的主档。另有姓名拼写变体档案，未与主档相加。",
      papers:[work("Geometry of the mapping class groups I: Boundary amenability",2008,"https://doi.org/10.1007/s00222-008-0158-2")],
      relevance:"与微分几何和动力系统交叉，具体课题匹配应进一步阅读。"
    },
    {
      id:"radu-laza", name:"Radu Laza", initials:"RL",
      affiliations:[affiliation("stony-brook","数学系","教授","https://www.math.stonybrook.edu/AlgebraicGeometry/")],
      fields:["complex","algebraic"], tags:["Hodge 理论","周期映射","Torelli","三次超曲面","模空间","紧化"],
      homepage:"https://www.math.stonybrook.edu/~rlaza/", cvUrl:"https://www.math.stonybrook.edu/~rlaza/resume.pdf",
      publicationsUrl:"https://www.math.stonybrook.edu/~rlaza/",
      metrics:openAlex("A5020748889","0000-0001-9631-1361",37,58,1268,21),
      identityNote:"用三次四维簇的周期映射论文与中间 Jacobian 紧化论文交叉核对。当前单位采用石溪任职页。",
      papers:[work("The moduli space of cubic fourfolds via the period map",2010,"https://doi.org/10.4007/annals.2010.172.673"),
        work("A hyper-Kähler compactification of the intermediate Jacobian fibration associated with a cubic 4-fold",2017,"https://doi.org/10.4310/ACTA.2017.v218.n1.a2")],
      relevance:"适合比较三次超曲面模空间、周期映射和紧化方法。所列论文研究三次四维簇，可用于理解周期方法。"
    },
    {
      id:"mark-mclean", name:"Mark McLean", initials:"MM",
      affiliations:[affiliation("stony-brook","数学系","教师","https://www.math.stonybrook.edu/faculty-areas-interest")],
      fields:["algebraic"], tags:["辛与接触几何","Reeb 动力学","辛同调","仿射簇","奇点"],
      homepage:"https://www.math.stonybrook.edu/~markmclean/index.html", cvUrl:"https://www.math.stonybrook.edu/sites/default/files/MCLEAN%20CV.pdf",
      publicationsUrl:"https://www.math.stonybrook.edu/~markmclean/index.html",
      metrics:openAlex("A5067728478","0000-0001-5565-785X",14,22,642,15),
      identityNote:"用 Stony Brook 任职及以下两篇 DOI 对应的作者记录核对。",
      papers:[work("Reeb orbits and the minimal discrepancy of an isolated singularity",2016,"https://link.springer.com/article/10.1007/s00222-015-0620-x"),
        work("The Growth Rate of Symplectic Homology and Affine Varieties",2012,"https://doi.org/10.1007/s00039-012-0158-7")],
      relevance:"可以从 Reeb 动力学、辛同调与仿射代数几何的交点出发，核对 Henry 论文的关键方法。"
    },
    {
      id:"gang-tian", name:"Gang Tian", nameZh:"田刚", initials:"GT",
      affiliations:[affiliation("pku","北京国际数学研究中心","教授","https://bicmr.pku.edu.cn/content/page/69.html")],
      fields:["complex","differential"], tags:["Kähler–Einstein 度量","Kähler–Ricci 流","辛几何","几何分析"],
      homepage:"https://tian.bicmr.pku.edu.cn/", cvUrl:"https://tian.bicmr.pku.edu.cn/Brief_CV.htm", cvType:"简版 CV",
      publicationsUrl:"https://tian.bicmr.pku.edu.cn/",
      metrics:openAlex("A5018414096","0000-0001-9876-8488",179,298,17486,65),
      identityNote:"用北大任职、Kähler–Einstein 与 Fano 流形研究的作者顺序和 DOI 核对。",
      papers:[work("Kähler-Einstein metrics with positive scalar curvature",1997,"https://doi.org/10.1007/s002220050176"),
        work("Horosymmetric limits of Kähler-Ricci flow on Fano G-manifolds",2022,"https://arxiv.org/abs/2209.05029")],
      relevance:"Kähler 几何、几何分析与辛几何交叉。"
    },
    {
      id:"qian-guan", name:"Qi’an Guan", nameZh:"关启安", initials:"QG",
      affiliations:[affiliation("pku","数学科学学院","教授","https://math.pku.edu.cn/jsdw/js_20180628175159671361/g_20180628175159671361/1081math69921.htm")],
      fields:["complex"], tags:["多复变","全纯延拓","L² 方法","乘子理想层"],
      homepage:null, cvUrl:null, cvStatus:"院系页提供教育经历、任职和代表论著。独立 CV 待查。",
      publicationsUrl:"https://math.pku.edu.cn/jsdw/js_20180628175159671361/g_20180628175159671361/1081math69921.htm",
      metrics:openAlex("A5102992506","0000-0002-6151-3059",47,76,1606,19),
      identityNote:"用北大任职、两篇不同的 Annals 论文与合作者核对。另有同名植物学作者。",
      papers:[work("A proof of Demailly's strong openness conjecture",2015,"https://doi.org/10.4007/annals.2015.182.2.5"),
        work("A solution of an L² extension problem with an optimal estimate and applications",2015,"https://doi.org/10.4007/annals.2015.181.3.6")],
      relevance:"与解析延拓和 L² 方法相邻。可用于判断补空间问题中增长与延拓条件的处理方式。"
    },
    {
      id:"xiaohua-zhu", name:"Xiaohua Zhu", nameZh:"朱小华", initials:"XZ",
      affiliations:[affiliation("pku","数学科学学院","教授","https://math.pku.edu.cn/puremath/szll/qtjy/z/83309.htm")],
      fields:["complex","differential"], tags:["典则 Kähler 度量","Kähler–Ricci 流","Ricci 孤立子","Fano"],
      homepage:null, cvUrl:null, cvStatus:"院系页有教育、任职和成果信息。独立 CV 待查。",
      bioUrl:"https://math.pku.edu.cn/mathalumni/yyxw/rdxw/141125.htm",
      publicationsUrl:"https://math.pku.edu.cn/puremath/szll/qtjy/z/83309.htm",
      metrics:[], identityNote:"Fano 论文找到候选作者 ID，但该档案也收录合金和材料论文。累计指标暂留待核。",
      identityUrl:"https://openalex.org/authors/A5101186383",
      papers:[work("Horosymmetric limits of Kähler-Ricci flow on Fano G-manifolds",2022,"https://arxiv.org/abs/2209.05029")],
      relevance:"可从典则度量、Fano 和 Kähler–Ricci 流判断与现有复几何工作的交叉。"
    }
  ].map(person => ({checkedAt, ...person}));
})();
