import type { Position } from '../types';
export const nf = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 2 });
export function countLabel(count: number, one: string, few: string, many: string) {
	const value = Math.abs(count) % 100;
	const last = value % 10;
	const label =
		value >= 11 && value <= 14 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many;
	return `${nf.format(count)} ${label}`;
}
export const cash = new Intl.NumberFormat('ru-BY', {
	minimumFractionDigits: 2,
	maximumFractionDigits: 2,
});
export function Currency() {
	return (
		<svg className="currency" viewBox="0 0 650 800" role="img" aria-label="белорусских рублей">
			<path
				fill="currentColor"
				fillRule="evenodd"
				d="M112 0H560V88H207V328H416C553 328 647 427 647 564S553 800 416 800H112V616H0V520H112V0ZM207 420V520H408V616H207V712H411C495 712 551 651 551 564S495 420 411 420H207Z"
			/>
		</svg>
	);
}
export function Money({ value }: { value: number }) {
	return (
		<span className="money">
			{cash.format(value)}
			<Currency />
		</span>
	);
}
export function unit(value: string) {
	return (
		({ м: 'м', шт: 'шт.', кг: 'кг', сист: 'сист.', компл: 'компл.' } as Record<string, string>)[
			value
		] || value
	);
}
export function shortName(p: Position) {
	if (p.name.startsWith('Фреонопровод медный'))
		return 'Фреонопровод медный ' + (p.name.match(/Д\s*[\d.,]+/)?.[0] || '');
	if (p.name.startsWith('Трубка теплоизоляционная'))
		return 'Теплоизоляция K-FLEX ' + (p.name.match(/Д\s*[\d.,]+/)?.[0] || '');
	if (p.name.startsWith('Кабель силовой'))
		return 'Кабель силовой ' + (p.name.match(/\d+[хx×][\d,]+/)?.[0] || '');
	return p.name;
}
