// Compatibility entry for the current production mind-map checks.
process.env.EDUCATION_OUTPUT ||= process.argv[2] || __dirname;
require('./education-mindmap-smoke.cjs');
