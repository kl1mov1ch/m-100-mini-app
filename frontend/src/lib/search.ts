const russian = 'абвгдежзийклмнопрстуфхцчшщъыьэюя';
const latin = [
	'a',
	'b',
	'v',
	'g',
	'd',
	'e',
	'zh',
	'z',
	'i',
	'i',
	'k',
	'l',
	'm',
	'n',
	'o',
	'p',
	'r',
	's',
	't',
	'u',
	'f',
	'kh',
	'ts',
	'ch',
	'sh',
	'shch',
	'',
	'y',
	'',
	'e',
	'yu',
	'ya',
];
const latinKeys = "qwertyuiop[]asdfghjkl;'zxcvbnm,.";
const cyrillicKeys = 'йцукенгшщзхъфывапролджэячсмитьбю';
const gloss =
	/^(kak|skolko|gde|naiti|nayti|pokazhi|naidi|kakaya|найди|найти|покажи|сколько|где|какой|какая|какие)$/u;
const normalize = (value: string) =>
	value
		.normalize('NFKC')
		.toLowerCase()
		.replaceAll('ё', 'е')
		.replace(/три на два с половиной|tri na dva s polovino[iy]/g, '3x2.5')
		.replace(/(\d)\s*[×хx]\s*(?=\d)/g, '$1x')
		.replace(/(?<=\d),(?=\d)/g, '.')
		.replace(/(?:[ø⌀]|\b(?:dn|d)|дн?)\s*(?=\d)/g, 'd');
const toLatin = (value: string) =>
	[...value]
		.map((char) => {
			const index = russian.indexOf(char);
			return index < 0 ? char : latin[index];
		})
		.join('')
		.replace(/(?:tsi|ci)(?=ya)/g, 'tsi')
		.replace(/(?:sch|shch)/g, 'shch')
		.replace(/kh/g, 'h')
		.replace(/(?:j|jj)/g, 'i');
const changeKeys = (value: string, from: string, to: string) =>
	[...value].map((char) => to[from.indexOf(char)] ?? char).join('');
const tokens = (value: string) => value.match(/[\p{L}\p{N}]+(?:\.\d+)?/gu) || [];
const numbers = (value: string) => value.match(/\d+(?:\.\d+)?/g) || [];

function resembles(left: string, right: string) {
	if (left.length < 3 || Math.abs(left.length - right.length) > 1) return false;
	if (left.length === right.length) {
		const different = [...left].flatMap((char, index) => (char === right[index] ? [] : [index]));
		return (
			different.length === 1 ||
			(different.length === 2 &&
				different[1] === different[0] + 1 &&
				left[different[0]] === right[different[1]] &&
				left[different[1]] === right[different[0]])
		);
	}
	const [short, long] = left.length < right.length ? [left, right] : [right, left];
	const index = [...short].findIndex((char, i) => char !== long[i]);
	return index === -1 || short.slice(index) === long.slice(index + 1);
}

function wordScore(term: string, words: string[], digits: Set<string>) {
	if (words.includes(term) || digits.has(term)) return 12;
	if (/\d/.test(term)) return -14;
	if (words.some((word) => word.startsWith(term))) return 9;
	if (words.some((word) => word.includes(term))) return 6;
	if (words.some((word) => resembles(term, word.slice(0, term.length + 1)))) return 4;
	return 0;
}

export function searchRank(query: string, raw: string) {
	const target = toLatin(normalize(raw));
	const words = tokens(target);
	const digits = new Set(numbers(target));
	const original = normalize(query);
	const queryWords = tokens(toLatin(original)).filter(
		(word) => word.length >= 3 && !gloss.test(word),
	);
	const near = queryWords.reduce((best, word) => {
		let pairs = 0;
		for (let index = 0; index < word.length - 1; index++)
			if (target.includes(word.slice(index, index + 2))) pairs++;
		return Math.max(best, Math.min(3, (pairs / (word.length - 1)) * 3));
	}, 0);
	const variants = [
		original,
		changeKeys(original, latinKeys, cyrillicKeys),
		changeKeys(original, cyrillicKeys, latinKeys),
	];
	return Math.max(
		near,
		...variants.map((value, index) => {
			const terms = tokens(toLatin(value)).filter((term) => !gloss.test(term));
			if (!terms.length) return 0;
			let score = 0,
				coverage = 0;
			for (const term of terms) {
				const match = wordScore(term, words, digits);
				if (match > 0) coverage++;
				score += match;
			}
			return score + (coverage === terms.length ? 8 : 0) - index;
		}),
	);
}

export function rankedSearch<T>(items: T[], query: string, label: (item: T) => string) {
	if (!query.trim()) return items.map((item) => ({ item, score: 0 }));
	return items
		.map((item) => ({ item, score: searchRank(query, label(item)) }))
		.sort((a, b) => b.score - a.score);
}

export const sortSearchOptions = (
	left: { label?: unknown },
	right: { label?: unknown },
	info: { searchValue: string },
) =>
	searchRank(info.searchValue, String(right.label ?? '')) -
	searchRank(info.searchValue, String(left.label ?? ''));
