// Regenerate compiler fixtures, with no Solidity compiler dependency in the package/CI.
// node compile.cjs /absolute/path/to/node_modules/solc
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const solc = require(process.argv[2]);
if (!solc.version().startsWith('0.8.30+')) throw Error('Use solc 0.8.30 for reproducibility');
const directory = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
const sources = Object.fromEntries(Object.values(manifest.examples).map(({source}) => [source, {
  content: fs.readFileSync(path.join(directory, source), 'utf8')
}]));
const settings = {outputSelection: {'*': {'*': ['abi', 'userdoc', 'devdoc']}}};
const output = JSON.parse(solc.compile(JSON.stringify({language: 'Solidity', sources, settings})));
const errors = (output.errors || []).filter(e => e.severity === 'error');
if (errors.length) throw Error(errors.map(e => e.formattedMessage).join('\n'));
for (const [name, {source, contract}] of Object.entries(manifest.examples)) {
  const result = output.contracts[source][contract];
  const artifact = {
    compilerVersion: solc.version(),
    sourceSha256: crypto.createHash('sha256').update(sources[source].content).digest('hex'),
    ...result
  };
  fs.writeFileSync(path.join(directory, name + '.artifact.json'), JSON.stringify(artifact, null, 2) + '\n');
}
