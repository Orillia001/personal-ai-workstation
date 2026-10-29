const fs = require("node:fs");
const path = require("node:path");
const source = path.resolve(__dirname, "../../../../Tools/site_adapters/rain_classroom_reader.js");
fs.copyFileSync(source, path.join(__dirname, "rain-reader.js"));
fs.copyFileSync(path.resolve(__dirname, "../../../../Tools/site_adapters/theol_homework_reader.js"),
  path.join(__dirname, "theol-reader.js"));
