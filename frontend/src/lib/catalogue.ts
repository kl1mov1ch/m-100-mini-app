import type { Position } from '../types';
import { unit } from './format';
import { positionOverrun } from './position-volume';

export type CatalogueCategory = 'all' | 'volume' | 'labour' | 'other';
export type CatalogueStatus = 'all' | 'remaining' | 'completed' | 'overrun';
export type CatalogueSort = 'source' | 'name' | 'remaining' | 'rate';
export const catalogueCategories = [
	{ value: 'all', label: 'Все', title: 'Все позиции' },
	{ value: 'volume', label: 'Объём', title: 'Объёмные работы' },
	{ value: 'labour', label: 'Труд', title: 'Трудозатраты' },
	{ value: 'other', label: 'Прочее', title: 'Прочие позиции' },
] as const;

export function catalogueCategory(
	position: Pick<Position, 'unit'>,
): Exclude<CatalogueCategory, 'all'> {
	const measure = unit(position.unit)
		.toLocaleLowerCase('ru')
		.replace(/[.\s_\\/−–-]/g, '')
		.replace('²', '2')
		.replace('³', '3');
	if (/чел|челов|час|машч|^ч$|день|дни|дн|сут|смен/.test(measure)) return 'labour';
	if (
		/^(м|мп|погм|м2|м3|мм|см|шт|штук[аи]?|кг|т|комп|компл|комплект|сист|система|систем|системы|ед)$/.test(
			measure,
		)
	)
		return 'volume';
	return 'other';
}

export function catalogueValues(position: Position) {
	return positionOverrun(position) || position.bitrix || position;
}

export function catalogueStatusMatches(position: Position, status: CatalogueStatus) {
	const values = catalogueValues(position);
	const excess = !!positionOverrun(position) || values.completed > values.planned + 1e-8;
	if (status === 'overrun') return excess;
	if (status === 'remaining') return !excess && values.planned - values.completed > 1e-8;
	if (status === 'completed')
		return !excess && values.planned > 0 && values.completed >= values.planned - 1e-8;
	return true;
}

export function selectCatalogue(
	positions: Position[],
	filters: {
		query: string;
		category: CatalogueCategory;
		status: CatalogueStatus;
		section: string;
		sort: CatalogueSort;
	},
) {
	const term = filters.query.trim().toLocaleLowerCase('ru');
	return positions
		.filter(
			(position) =>
				(filters.category === 'all' || catalogueCategory(position) === filters.category) &&
				(filters.section === 'all' || position.section === filters.section) &&
				catalogueStatusMatches(position, filters.status) &&
				[position.name, position.section, position.source_sheet]
					.filter(Boolean)
					.join(' ')
					.toLocaleLowerCase('ru')
					.includes(term),
		)
		.sort((left, right) => {
			const excessOrder =
				Number(catalogueStatusMatches(left, 'overrun')) -
				Number(catalogueStatusMatches(right, 'overrun'));
			if (excessOrder) return excessOrder;
			if (filters.sort === 'name')
				return left.name.localeCompare(right.name, 'ru', { numeric: true });
			if (filters.sort === 'rate') return catalogueValues(right).rate - catalogueValues(left).rate;
			if (filters.sort === 'remaining') {
				const a = catalogueValues(left),
					b = catalogueValues(right);
				return b.planned - b.completed - (a.planned - a.completed);
			}
			return (
				(left.source_sheet || '').localeCompare(right.source_sheet || '', 'ru') ||
				left.source_row - right.source_row
			);
		});
}
