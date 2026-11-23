import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const asset = name => readFileSync(new URL(`./dist/${name}`, import.meta.url), "utf8");
const scripts = ["schools.js", "faculty.js", "collection.js", "app.js"];
let page = asset("index.html");
const stylesheet = '<link rel="stylesheet" href="styles.css">';
if (!page.includes(stylesheet)) throw new Error("The index must reference styles.css.");
page = page.replace(stylesheet, () => `<style>\n${asset("styles.css")}\n</style>`);
for (const script of scripts) {
  const tag = `<script defer src="${script}"></script>`;
  if (!page.includes(tag)) throw new Error(`The index must reference ${script}.`);
  page = page.replace(tag, "");
}
const prompt = Buffer.from(asset("research-prompt.md"), "utf8").toString("base64");
page = page.replace('href="research-prompt.md"', `href="data:text/markdown;charset=utf-8;base64,${prompt}"`);
const inlined = scripts.map(script => {
  const source = asset(script).replace(/<\/script/gi, "<\\/script");
  return `<script>\n${source}\n</script>`;
}).join("\n");
page = page.replace("</body>", () => `${inlined}\n</body>`);
const destination = fileURLToPath(new URL("./geometry-faculty-atlas.html", import.meta.url));
writeFileSync(destination, page, "utf8");
console.log(`Single-file directory written to ${destination}`);
