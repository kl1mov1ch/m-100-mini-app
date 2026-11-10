import fs from 'node:fs';
import path from 'node:path';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const projectRoot = path.resolve('frontend');
const configPath = path.join(projectRoot, 'tsconfig.json');
const config = ts.readConfigFile(configPath, ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, projectRoot);
const options = { ...parsed.options, noUnusedLocals: true };
const files = parsed.fileNames.filter(
	(name) =>
		name.includes(path.join('src', path.sep)) || name.includes('/src/') || name.includes('\\src\\'),
);
const host = {
	getScriptFileNames: () => files,
	getScriptVersion: (file) => String(fs.statSync(file).mtimeMs),
	getScriptSnapshot: (file) => {
		const content = ts.sys.readFile(file);
		return content === undefined ? undefined : ts.ScriptSnapshot.fromString(content);
	},
	getCurrentDirectory: () => projectRoot,
	getCompilationSettings: () => options,
	getDefaultLibFileName: (settings) => ts.getDefaultLibFilePath(settings),
	fileExists: ts.sys.fileExists,
	readFile: ts.sys.readFile,
	readDirectory: ts.sys.readDirectory,
};
const service = ts.createLanguageService(host);
function apply(changes) {
	for (const change of changes) {
		let source = fs.readFileSync(change.fileName, 'utf8');
		for (const replacement of [...change.textChanges].sort((a, b) => b.span.start - a.span.start))
			source =
				source.slice(0, replacement.span.start) +
				replacement.newText +
				source.slice(replacement.span.start + replacement.span.length);
		fs.writeFileSync(change.fileName, source);
	}
}
for (const file of files) {
	const source = fs.readFileSync(file, 'utf8');
	const syntax = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
	const replacements = [];
	for (const declaration of syntax.statements) {
		if (!ts.isFunctionDeclaration(declaration) || !declaration.body) continue;
		const first = declaration.body.statements.find(
			(statement) =>
				ts.isVariableStatement(statement) &&
				ts.isObjectBindingPattern(statement.declarationList.declarations[0].name),
		);
		if (!first) continue;
		const binding = first.declarationList.declarations[0];
		if (!ts.isObjectBindingPattern(binding.name)) continue;
		const used = new Set();
		function visit(node) {
			if (ts.isIdentifier(node)) used.add(node.text);
			ts.forEachChild(node, visit);
		}
		for (const statement of declaration.body.statements) if (statement !== first) visit(statement);
		const kept = binding.name.elements
			.filter((element) => used.has(element.name.getText(syntax)))
			.map((element) => element.getText(syntax));
		replacements.push({
			span: { start: binding.name.getStart(syntax), length: binding.name.getWidth(syntax) },
			newText: '{' + kept.join(',') + '}',
		});
	}
	if (replacements.length) apply([{ fileName: file, textChanges: replacements }]);
	apply(service.organizeImports({ type: 'file', fileName: file }, {}, {}));
}
